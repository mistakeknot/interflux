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


def json_strings(value) -> list[str]:
    """Every string in a decoded JSON value, object keys included."""
    out: list[str] = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            for key, child in item.items():
                out.append(key)
                stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)
    return out


def decoded_view(data: bytes, name: str) -> str | None:
    """Decoded JSON string view for .json/.jsonl bytes; None when not applicable or unparseable."""
    text = data.decode("utf-8", errors="replace")
    lowered = name.lower()
    strings: list[str] = []
    if lowered.endswith(".json"):
        try:
            strings = json_strings(json.loads(text))
        except ValueError:
            return None
    elif lowered.endswith(".jsonl"):
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                strings.extend(json_strings(json.loads(line)))
            except ValueError:
                strings.append(line)
    else:
        return None
    return "\n".join(strings)


def bytes_have_residue(scrub, binary: str | None, data: bytes, name: str) -> tuple[bool, bool]:
    """Return (residue, failed). A scrubber hit is residue even when Gitleaks failed."""
    if not data:
        return False, False
    text = data.decode("utf-8", errors="replace")
    views: list[bytes] = [data]
    decoded = decoded_view(data, name)
    residue = scrub(text) != text
    if decoded is not None:
        residue = residue or scrub(decoded) != decoded
        views.append(decoded.encode("utf-8"))
    failed = False
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


def walk_files(root: Path):
    """Yield (relative path, absolute path) for each regular file. Unsafe entries raise."""
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise ScannerFailure("unreadable directory") from exc
        for entry in entries:
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise ScannerFailure("unreadable entry") from exc
            full = Path(entry.path)
            if stat.S_ISDIR(mode):
                pending.append(full)
            elif stat.S_ISREG(mode):
                yield full.relative_to(root), full
            else:
                raise ScannerFailure("unsafe entry in run tree (symlink or special file)")


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
        for relative, full in walk_files(run):
            try:
                data = full.read_bytes()
            except OSError:
                print("scanner failure: unreadable file", file=sys.stderr)
                failure = True
                continue
            found, failed = bytes_have_residue(scrub, binary, data, full.name)
            if found:
                residue_files.append(scrub(str(relative)))
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
