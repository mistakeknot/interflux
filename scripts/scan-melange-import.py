#!/usr/bin/env python3
"""Post-import residue scan for a flux-melange run directory.

Usage (always under isolated mode):
    python3 -I scan-melange-import.py --run-dir <run>

Walks the whole run tree (state, ledger, imports, synthesis, hidden files) and
flags residual secrets with two independent detectors: the shared scrubber
(residue means the scrubber would change the text) and a pinned Gitleaks run
over the same bytes. Each JSON and JSONL file is also checked through its
decoded string view, keys included, so escaped secrets are found.

Read-only. Never prints matched text. Exit codes:
    0  clean
    2  invalid arguments
    20 residual secret
    22 scanner failure (missing/wrong Gitleaks, unsafe entry, unreadable file)
    23 invalid run directory
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_RESIDUE = 20
EXIT_SCANNER = 22
EXIT_INVALID_RUN = 23

GITLEAKS_VERSION = "8.30.1"
GITLEAKS_TIMEOUT = 60
CONFIG_RELATIVE = Path("config") / "flux-melange" / "import-gitleaks.toml"
HOOK_RELATIVE = Path("hooks") / "redact-melange-write.py"


class ScannerFailure(Exception):
    """The scan could not be completed. Never treated as a pass."""


def plugin_root() -> Path:
    # Under `python3 -I` the script directory is not on sys.path. Everything this
    # module needs is loaded explicitly from the plugin tree beside it.
    return Path(os.path.realpath(__file__)).parents[1]


def load_regular_module(name: str, relative: Path):
    root = plugin_root()
    path = root / relative
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ScannerFailure(f"missing helper {relative}") from exc
    if not stat.S_ISREG(info.st_mode) or os.path.realpath(path) != str(path):
        raise ScannerFailure(f"helper {relative} must be a regular file inside the plugin root")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ScannerFailure(f"cannot load helper {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return module


def load_scrub():
    return load_regular_module("melange_scan_hook", HOOK_RELATIVE).scrub


def config_path() -> Path:
    path = plugin_root() / CONFIG_RELATIVE
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ScannerFailure("scanner configuration is missing") from exc
    if not stat.S_ISREG(info.st_mode) or os.path.realpath(path) != str(path):
        raise ScannerFailure("scanner configuration must be a regular file inside the plugin root")
    return path


GITLEAKS_ENV_OVERRIDES = ("GITLEAKS_CONFIG", "GITLEAKS_CONFIG_TOML")


def gitleaks_environment() -> dict[str, str]:
    """Environment for Gitleaks with every GITLEAKS_* override removed."""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in GITLEAKS_ENV_OVERRIDES and not key.upper().startswith("GITLEAKS")
    }


def locate_gitleaks() -> str:
    env = gitleaks_environment()
    found = shutil.which("gitleaks", path=env.get("PATH", ""))
    if not found:
        home = env.get("HOME")
        candidate = Path(home) / ".local" / "bin" / "gitleaks" if home else None
        if candidate is not None and candidate.is_file() and os.access(candidate, os.X_OK):
            found = str(candidate)
    if not found:
        raise ScannerFailure("gitleaks is not installed")
    return found


def check_gitleaks(binary: str) -> None:
    try:
        proc = subprocess.run(
            [binary, "version"],
            capture_output=True,
            text=True,
            timeout=GITLEAKS_TIMEOUT,
            env=gitleaks_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScannerFailure("gitleaks version check failed") from exc
    if proc.returncode != 0 or proc.stdout.strip() != GITLEAKS_VERSION:
        raise ScannerFailure(f"gitleaks {GITLEAKS_VERSION} is required")


def gitleaks_flags(binary: str, data: bytes) -> bool:
    """True when Gitleaks reports a leak in the bytes. Raises ScannerFailure on any fault."""
    config = config_path()
    with tempfile.TemporaryDirectory(prefix="melange-scan-") as empty:
        os.chmod(empty, 0o700)
        argv = [
            binary,
            "stdin",
            "-c",
            str(config),
            "--ignore-gitleaks-allow",
            "-i",
            empty,
            "--max-decode-depth",
            "0",
            "--max-archive-depth",
            "0",
            "--redact=100",
            "--report-format",
            "json",
            "--report-path",
            "-",
            "--exit-code",
            "20",
            "--no-banner",
            "--no-color",
        ]
        try:
            proc = subprocess.run(
                argv,
                input=data,
                capture_output=True,
                timeout=GITLEAKS_TIMEOUT,
                env=gitleaks_environment(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ScannerFailure("gitleaks run failed") from exc
    if proc.returncode == 0:
        return False
    if proc.returncode == 20:
        return True
    raise ScannerFailure(f"gitleaks exited {proc.returncode}")


class Pairs(list):
    """A JSON object kept as its (key, value) pairs, so duplicate keys all survive."""


def json_strings(value) -> list[str]:
    """Every string in a decoded JSON value, object keys and duplicate-key values included."""
    out: list[str] = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, Pairs):
            for key, child in item:
                out.append(key)
                stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)
    return out


ESCAPE = re.compile(r"\\(?:u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8})|x([0-9a-fA-F]{2}))")
MAX_DECODE_PASSES = 64


def unescape_text(text: str) -> str:
    """Decode \\uXXXX, \\UXXXXXXXX and \\xXX sequences until nothing changes.

    A code point that cannot be shown as plain text (a control character, a surrogate or a
    value beyond U+10FFFF) becomes the visible placeholder `[encoded U+XXXX]` instead of a
    character, so it neither changes line structure nor leaves a hexadecimal digit next to a
    secret (which would hide the secret from the identifier boundary). Escapes nested more
    than MAX_DECODE_PASSES deep cannot be proven clean: that raises ScannerFailure.
    """

    def one(match: re.Match[str]) -> str:
        point = int(match.group(1) or match.group(2) or match.group(3), 16)
        if point < 0x20 or 0x7F <= point <= 0x9F or point > 0x10FFFF or 0xD800 <= point <= 0xDFFF:
            return f"[encoded U+{point:04X}]"
        return chr(point)

    for _ in range(MAX_DECODE_PASSES):
        decoded = ESCAPE.sub(one, text)
        if decoded == text:
            return text
        text = decoded
    if ESCAPE.search(text) is None:
        return text
    raise ScannerFailure("escape sequences are nested too deeply to resolve")


def decoded_view(data: bytes, name: str) -> str | None:
    """Decoded JSON string view for .json/.jsonl bytes; None when not applicable or unparseable."""
    text = data.decode("utf-8", errors="replace")
    lowered = name.lower()
    strings: list[str] = []
    if lowered.endswith(".json"):
        try:
            strings = json_strings(json.loads(text, object_pairs_hook=Pairs))
        except ValueError:
            return None
        except RecursionError as exc:
            raise ScannerFailure("JSON is nested too deeply to decode") from exc
    elif lowered.endswith(".jsonl"):
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                strings.extend(json_strings(json.loads(line, object_pairs_hook=Pairs)))
            except ValueError:
                strings.append(line)
            except RecursionError as exc:
                raise ScannerFailure("JSON is nested too deeply to decode") from exc
    else:
        return None
    return "\n".join(strings)


RUN_LIMIT = 4096
LONG_RUN = re.compile(r"[A-Za-z0-9_-]{4097,}")
HYPHEN_START = re.compile(r"-eyJ")


def _shorten_run(match: re.Match[str]) -> str:
    """Bound one long base64url run, keeping the first place a JWT could start in it.

    A JWT may start at the run's first character (unless a dot precedes it) or right after a
    hyphen inside the run. Every such start sees the same tail (the rest of the run, then its
    dot-separated segments), so keeping the earliest admissible start with the head of its
    header is enough to preserve the shape; later starts add nothing. The result is at most
    two heads long however many starts the run holds.
    """
    run = match.group(0)
    before = match.string[match.start() - 1] if match.start() > 0 else ""
    start = 0 if run.startswith("eyJ") and before != "." else -1
    if start < 0:
        found = HYPHEN_START.search(run)
        if found is None:
            return run[:RUN_LIMIT]
        start = found.start() + 1
    lead = run[: min(start, RUN_LIMIT)]
    if start > 0 and not lead.endswith("-"):
        lead += "-"  # the hyphen that made this start admissible
    return lead + run[start : start + RUN_LIMIT]


def shrink_long_runs(text: str) -> str:
    """Bound each run of base64url characters longer than 4096.

    Gitleaks reads its input in roughly 100 KB chunks, so a token whose segment is longer than
    a chunk is never matched whole, and a chunk end can fake a token ending. A JWT needs only
    a few characters per segment to be recognised, so the bounded text keeps its shape. When
    a view holds such a run, Gitleaks is given the bounded text instead of the raw one; the
    Python scrubber still sees every view whole.
    """
    return LONG_RUN.sub(_shorten_run, text)


def bytes_have_residue(scrub, binary: str | None, data: bytes, name: str) -> tuple[bool, bool]:
    """Return (residue, failed). A scrubber hit is residue even when Gitleaks failed."""
    if not data:
        return False, False
    text = data.decode("utf-8", errors="replace")
    views: list[bytes] = [data]
    residue = scrub(text) != text
    candidates = [text]
    failed = False
    try:
        decoded = decoded_view(data, name)
    except ScannerFailure:
        decoded, failed = None, True
    if decoded is not None:
        residue = residue or scrub(decoded) != decoded
        # A lone surrogate from a JSON escape cannot be encoded: it becomes a replacement mark.
        views.append(decoded.encode("utf-8", errors="replace"))
        candidates.append(decoded)
    for candidate in candidates:
        try:
            unescaped = unescape_text(candidate)
        except ScannerFailure:
            failed = True
            continue
        if unescaped != candidate:
            residue = residue or scrub(unescaped) != unescaped
            views.append(unescaped.encode("utf-8", errors="replace"))
    for index, view in enumerate(views):
        original = view.decode("utf-8", errors="replace")
        shrunk = shrink_long_runs(original)
        if shrunk != original:
            views[index] = shrunk.encode("utf-8", errors="replace")
    if binary is None:
        return residue, True
    for view in views:
        try:
            if gitleaks_flags(binary, view):
                residue = True
        except ScannerFailure:
            failed = True
    return residue, failed


def validate_run(run_arg: str) -> Path:
    path = Path(run_arg)
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ScannerFailure("run directory does not exist") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise ScannerFailure("run directory is not a directory")
    real = Path(os.path.realpath(path))
    if real.parent.name != "flux-melange" or real.parents[1].name != "research" or real.parents[2].name != "docs":
        raise ScannerFailure("run directory is not under docs/research/flux-melange")
    for required in ("melange-state.json", "heat-ledger.jsonl"):
        try:
            if not stat.S_ISREG(os.lstat(real / required).st_mode):
                raise ScannerFailure(f"{required} is not a regular file")
        except OSError as exc:
            raise ScannerFailure(f"{required} is missing") from exc
    return real


def _open_nofollow(name: str, dir_fd: int, flags: int) -> int:
    return os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)


def walk_files(root: Path | None, root_fd: int | None = None):
    """Yield (relative path, bytes) for each regular file, reading through pinned directory descriptors.

    Every directory and file is opened with O_NOFOLLOW relative to its parent descriptor,
    and the descriptor's own stat decides the type, so an entry swapped for a symlink
    after listing is refused instead of followed. Unsafe entries raise ScannerFailure.
    """
    try:
        if root_fd is not None:
            root_fd = os.dup(root_fd)  # the caller keeps its own descriptor
        else:
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ScannerFailure("unreadable run directory") from exc
    pending: list[tuple[int, str]] = [(root_fd, "")]
    try:
        while pending:
            dir_fd, prefix = pending.pop()
            try:
                with os.scandir(dir_fd) as listing:
                    entries = sorted(((e.name, e.stat(follow_symlinks=False).st_mode) for e in listing))
            except OSError as exc:
                os.close(dir_fd)
                raise ScannerFailure("unreadable directory") from exc
            try:
                for name, mode in entries:
                    relative = prefix + name
                    if stat.S_ISDIR(mode):
                        try:
                            child = _open_nofollow(name, dir_fd, os.O_RDONLY | os.O_DIRECTORY)
                        except OSError as exc:
                            raise ScannerFailure("unsafe entry in run tree (replaced or unreadable directory)") from exc
                        pending.append((child, relative + "/"))
                    elif stat.S_ISREG(mode):
                        try:
                            fd = _open_nofollow(name, dir_fd, os.O_RDONLY | os.O_NONBLOCK)
                        except OSError as exc:
                            raise ScannerFailure("unsafe entry in run tree (replaced or unreadable file)") from exc
                        try:
                            if not stat.S_ISREG(os.fstat(fd).st_mode):
                                raise ScannerFailure("unsafe entry in run tree (replaced file)")
                            with os.fdopen(fd, "rb", closefd=False) as handle:
                                data = handle.read()
                        finally:
                            os.close(fd)
                        yield relative, data
                    else:
                        raise ScannerFailure("unsafe entry in run tree (symlink or special file)")
            finally:
                os.close(dir_fd)
    finally:
        for dir_fd, _ in pending:
            try:
                os.close(dir_fd)
            except OSError:
                pass


def parse_args(argv: list[str]) -> str | None:
    if len(argv) != 2 or argv[0] != "--run-dir" or not argv[1]:
        return None
    return argv[1]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    run_arg = parse_args(args)
    if run_arg is None:
        print("usage: scan-melange-import.py --run-dir <run>", file=sys.stderr)
        return EXIT_USAGE
    try:
        run = validate_run(run_arg)
    except ScannerFailure as exc:
        print(f"invalid run: {exc}", file=sys.stderr)
        return EXIT_INVALID_RUN
    try:
        scrub = load_scrub()
    except Exception as exc:  # helper load faults are scanner faults
        print(f"scanner failure: {exc}", file=sys.stderr)
        return EXIT_SCANNER
    binary: str | None
    failure = False
    try:
        binary = locate_gitleaks()
        check_gitleaks(binary)
        config_path()
    except ScannerFailure as exc:
        print(f"scanner failure: {exc}", file=sys.stderr)
        binary = None
        failure = True
    residue_files: list[str] = []
    try:
        for relative, data in walk_files(run):
            found, failed = bytes_have_residue(scrub, binary, data, os.path.basename(relative))
            if found:
                residue_files.append(scrub(relative))
            failure = failure or failed
    except ScannerFailure as exc:
        print(f"scanner failure: {exc}", file=sys.stderr)
        failure = True
    if residue_files:
        print(f"residual secret detected in {len(residue_files)} file(s):", file=sys.stderr)
        for name in sorted(residue_files):
            print(f"  {name}", file=sys.stderr)
        return EXIT_RESIDUE
    if failure:
        return EXIT_SCANNER
    print("clean")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
