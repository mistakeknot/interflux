#!/usr/bin/env python3
"""Import a separately packaged cross-lab review into an existing flux-melange run.

Usage (always under isolated mode):
    python3 -I import-melange-review.py --run-dir <run> --receipt <receipt.json> \
        --report <report.md> --report-sha256 <64 lowercase hex>

The importer is deterministic. It reads one review receipt and one review report,
checks them (receipt shape, lab independence, operator-supplied report hash, report
grammar, verdict agreement), scrubs every named secret form in memory, scans the
serialized bytes, and only then stages and publishes one bundle:

    <run>/imports/<id>/{manifest.json, findings.jsonl,
                        findings/fd-external-review-<id>.md,
                        external-evidence/receipt.redacted.json,
                        external-evidence/report.redacted.md}

Imported findings are raw and unverified. The receipt is evidence about a pull
request, not proof about this run: the binding recorded in the manifest says exactly
what was checked and what was not. Nothing here edits the run state or the ledger.

Exit codes:
    0  complete import, exact existing import revalidated
    2  invalid arguments, hash form, unsafe input path or input replaced mid-read
    10 receipt missing, unreadable, invalid or misnamed
    11 report hash does not match the supplied hash
    12 lab admission failure
    13 unsupported report or extraction failure
    14 scrub, serialization, structural or provenance failure
    15 verdict disagreement
    16 late or second import
    20 residual secret
    21 busy, conflict, filesystem mismatch or tampered existing bundle
    22 scanner failure
    23 missing or invalid run
    24 report missing, unreadable or I/O failure
"""

from __future__ import annotations

import ctypes
import datetime
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_RECEIPT = 10
EXIT_HASH = 11
EXIT_LAB = 12
EXIT_REPORT = 13
EXIT_SCRUB = 14
EXIT_VERDICT = 15
EXIT_LATE = 16
EXIT_RESIDUE = 20
EXIT_CONFLICT = 21
EXIT_SCANNER = 22
EXIT_RUN = 23
EXIT_IO = 24

RECEIPT_CAP = 1 << 20
REPORT_CAP = 16 << 20
OPTIONS = ("--run-dir", "--receipt", "--report", "--report-sha256")
BUNDLE_SCHEMA = b"melange-import-v3\0"
STAGING_RELATIVE = (".clavain", "melange-import-staging")
RENAME_NOREPLACE = 1

BINDING_LABEL = "coordinator-asserted, receipt-consistent (verdict only)"
APPLICABILITY_NOTE = (
    "PR-bound receipt; applicability to this run is not established. "
    "Coordinator justification is required before assimilation."
)
NOT_IN_RECEIPT = "not in receipt"

MESSAGES = {
    EXIT_USAGE: "invalid arguments or unsafe input",
    EXIT_RECEIPT: "receipt missing or invalid",
    EXIT_HASH: "report hash mismatch",
    EXIT_LAB: "lab admission failed",
    EXIT_REPORT: "unsupported report",
    EXIT_SCRUB: "scrub, serialization or provenance failure",
    EXIT_VERDICT: "verdict disagreement",
    EXIT_LATE: "late or second import",
    EXIT_RESIDUE: "residual secret detected; nothing published",
    EXIT_CONFLICT: "busy, conflicting or tampered import state",
    EXIT_SCANNER: "scanner failure",
    EXIT_RUN: "missing or invalid run",
    EXIT_IO: "report missing or unreadable",
}


class ImportFailure(Exception):
    """An import step failed. `code` is the process exit code."""

    def __init__(self, code: int, reason: str = ""):
        super().__init__(reason or MESSAGES.get(code, "import failed"))
        self.code = code
        self.reason = reason or MESSAGES.get(code, "import failed")


# ---------------------------------------------------------------- helper loading

_HELPERS: dict = {}


def plugin_root() -> Path:
    # Under `python3 -I` the script directory is not on sys.path. Every helper is
    # loaded explicitly from the plugin tree that holds this file.
    return Path(os.path.realpath(__file__)).parents[1]


def _load_regular(name: str, relative: str):
    root = plugin_root()
    path = root / relative
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ImportFailure(EXIT_SCRUB, f"missing helper {relative}") from exc
    if not stat.S_ISREG(info.st_mode) or os.path.realpath(path) != str(path):
        raise ImportFailure(EXIT_SCRUB, f"helper {relative} must be a regular file inside the plugin root")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportFailure(EXIT_SCRUB, f"cannot load helper {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ImportFailure(EXIT_SCRUB, f"cannot load helper {relative}") from exc
    return module


def helpers() -> dict:
    if not _HELPERS:
        loaded = {
            "sanitize": _load_regular("melange_import_sanitize", "scripts/sanitize_untrusted.py"),
            "hook": _load_regular("melange_import_hook", "hooks/redact-melange-write.py"),
            "scanner": _load_regular("melange_import_scanner", "scripts/scan-melange-import.py"),
        }
        _HELPERS.update(loaded)
    return _HELPERS


def scrub(value: str) -> str:
    """The shared scrubber. Looked up at call time; a helper fault is exit 14."""
    try:
        return helpers()["hook"].scrub(value)
    except ImportFailure:
        raise
    except Exception as exc:
        raise ImportFailure(EXIT_SCRUB, "scrubber fault") from exc


def sanitize(text: str) -> str:
    try:
        return str(helpers()["sanitize"].sanitize(text, 0))
    except ImportFailure:
        raise
    except Exception as exc:
        raise ImportFailure(EXIT_SCRUB, "sanitizer fault") from exc


# --------------------------------------------------------------------- utilities


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def scrub_json_value(value):
    """Scrub every string in a decoded JSON value, object keys included."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, list):
        return [scrub_json_value(item) for item in value]
    if isinstance(value, dict):
        return {scrub(key): scrub_json_value(item) for key, item in value.items()}
    return value


def canonical_scrubbed(value) -> bytes:
    """Canonical JSON bytes that the scrubber leaves unchanged (re-parsed after scrubbing)."""
    value = scrub_json_value(value)
    for _ in range(3):
        data = canonical(value)
        text = data.decode("utf-8")
        scrubbed = scrub(text)
        if scrubbed == text:
            return data
        try:
            value = json.loads(scrubbed)
        except ValueError as exc:
            raise ImportFailure(EXIT_SCRUB, "scrub broke JSON serialization") from exc
    raise ImportFailure(EXIT_SCRUB, "scrub did not converge")


def parse_args(argv: list[str]) -> dict[str, str]:
    if "--receipt" not in argv:
        raise ImportFailure(EXIT_RECEIPT, "--receipt is required")
    values: dict[str, str] = {}
    index = 0
    while index < len(argv):
        option = argv[index]
        if option not in OPTIONS or option in values or index + 1 >= len(argv) or not argv[index + 1]:
            raise ImportFailure(EXIT_USAGE)
        values[option] = argv[index + 1]
        index += 2
    if "--report" not in values or "--report-sha256" not in values or "--run-dir" not in values:
        raise ImportFailure(EXIT_USAGE)
    if not re.fullmatch(r"[0-9a-f]{64}", values["--report-sha256"]):
        raise ImportFailure(EXIT_USAGE)
    return values


def check_path_text(value: str) -> None:
    if "$" in value or "`" in value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ImportFailure(EXIT_USAGE)


def precheck_input(value: str) -> None:
    """Path safety for the receipt and report: not in the melange tree, no symlink or special file."""
    check_path_text(value)
    full = os.path.join(os.getcwd(), value)
    parent, name = os.path.split(full)
    if not name:
        raise ImportFailure(EXIT_USAGE)
    parts = Path(os.path.realpath(parent)).parts + (name,)
    for index in range(len(parts) - 2):
        if parts[index : index + 3] == ("docs", "research", "flux-melange"):
            raise ImportFailure(EXIT_USAGE)
    try:
        info = os.lstat(full)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ImportFailure(EXIT_USAGE) from exc
    if not stat.S_ISREG(info.st_mode):
        raise ImportFailure(EXIT_USAGE)


def read_input(value: str, cap: int, *, missing: int, oversize: int, ioerr: int) -> bytes:
    path = os.path.join(os.getcwd(), value)
    try:
        before = os.lstat(path)
    except FileNotFoundError as exc:
        raise ImportFailure(missing) from exc
    except OSError as exc:
        raise ImportFailure(ioerr) from exc
    if not stat.S_ISREG(before.st_mode):
        raise ImportFailure(EXIT_USAGE)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        raise ImportFailure(ioerr) from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ImportFailure(EXIT_USAGE)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                raise ImportFailure(oversize)
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise ImportFailure(ioerr) from exc
    finally:
        os.close(fd)


def validate_run(value: str) -> tuple[Path, Path]:
    """Return (real run directory, project root). Exit 23 for anything else."""
    path = Path(os.path.join(os.getcwd(), value))
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ImportFailure(EXIT_RUN) from exc
    if not stat.S_ISDIR(info.st_mode):
        raise ImportFailure(EXIT_RUN)
    real = Path(os.path.realpath(path))
    if len(real.parents) < 4 or real.parent.name != "flux-melange" or real.parents[1].name != "research" or real.parents[2].name != "docs":
        raise ImportFailure(EXIT_RUN)
    for required in ("melange-state.json", "heat-ledger.jsonl"):
        try:
            if not stat.S_ISREG(os.lstat(real / required).st_mode):
                raise ImportFailure(EXIT_RUN)
        except OSError as exc:
            raise ImportFailure(EXIT_RUN) from exc
    return real, real.parents[3]


# ----------------------------------------------------------------------- receipt

RECEIPT_KEYS = (
    "schema_version", "kind", "role", "repo", "repo_id", "pr", "head_sha", "head_tree", "base_sha",
    "expected_merge_tree", "diff_sha256", "policy_hash", "diff_stat", "producer_identity",
    "reviewer_identity", "validator_relationship", "dispatch_id", "attempt_id", "verdict",
    "created_at", "sequence",
)
RECEIPT_VERDICTS = ("PASS", "PASS WITH NOTES", "BLOCK")
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
REPO_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
REPO_ID_RE = re.compile(r"[A-Za-z0-9_=-]+")
CREATED_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{9}Z")


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _reject_constant(name):
    raise ValueError("non-finite number")


def _is_int(value) -> bool:
    return type(value) is int


def validate_receipt(data: bytes) -> dict:
    try:
        text = data.decode("utf-8")
        receipt = json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ImportFailure(EXIT_RECEIPT, "receipt is not valid JSON") from exc
    if not isinstance(receipt, dict) or set(receipt) != set(RECEIPT_KEYS):
        raise ImportFailure(EXIT_RECEIPT, "receipt fields do not match the schema")

    def bad(reason: str):
        raise ImportFailure(EXIT_RECEIPT, reason)

    if not _is_int(receipt["schema_version"]) or receipt["schema_version"] != 1:
        bad("schema_version")
    if receipt["kind"] != "cross-lab-review-receipt" or receipt["role"] != "cross-lab-review":
        bad("kind or role")
    repo = receipt["repo"]
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo) or any(part in (".", "..") for part in repo.split("/")):
        bad("repo")
    if not isinstance(receipt["repo_id"], str) or not REPO_ID_RE.fullmatch(receipt["repo_id"]):
        bad("repo_id")
    pr = receipt["pr"]
    if not _is_int(pr) or not 1 <= pr <= 999999999:
        bad("pr")
    for key in ("head_sha", "head_tree", "base_sha", "expected_merge_tree"):
        if not isinstance(receipt[key], str) or not HEX40.fullmatch(receipt[key]):
            bad(key)
    for key in ("diff_sha256", "policy_hash"):
        if not isinstance(receipt[key], str) or not HEX64.fullmatch(receipt[key]):
            bad(key)
    if not isinstance(receipt["diff_stat"], str):
        bad("diff_stat")
    for key in ("producer_identity", "reviewer_identity"):
        if not isinstance(receipt[key], str) or not receipt[key]:
            bad(key)
    for key in ("validator_relationship", "dispatch_id", "attempt_id"):
        value = receipt[key]
        if value is not None and (not isinstance(value, str) or not value):
            bad(key)
    if receipt["verdict"] not in RECEIPT_VERDICTS:
        bad("verdict")
    created = receipt["created_at"]
    if not isinstance(created, str) or not CREATED_RE.fullmatch(created):
        bad("created_at")
    try:
        datetime.datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        bad("created_at")
    sequence = receipt["sequence"]
    if not _is_int(sequence) or not 1 <= sequence <= 999:
        bad("sequence")
    return receipt


def receipt_basename(receipt: dict) -> str:
    suffix = "" if receipt["sequence"] == 1 else f".{receipt['sequence']}"
    return f"{receipt['pr']}-{receipt['head_sha']}{suffix}.json"


LAB_PREFIXES = (
    ("anthropic", ("claude", "anthropic", "opus", "sonnet", "haiku", "fable")),
    ("openai", ("gpt", "codex", "openai", "astra", "sol")),
    ("moonshot", ("kimi", "moonshot")),
    ("google", ("gemini", "google")),
)


def lab_of(identity) -> str:
    """Case-insensitive prefix mapping. Decorations are not stripped; the rest is unknown."""
    if not isinstance(identity, str):
        return "unknown"
    lowered = identity.lower()
    if re.match(r"o[0-9]", lowered):
        return "openai"
    for lab, prefixes in LAB_PREFIXES:
        if lowered.startswith(prefixes):
            return lab
    return "unknown"


def admit_labs(receipt: dict) -> tuple[str, str]:
    reviewer = lab_of(receipt["reviewer_identity"])
    producer = lab_of(receipt["producer_identity"])
    if reviewer != "openai" or producer == "unknown" or producer == reviewer:
        raise ImportFailure(EXIT_LAB)
    return reviewer, producer


# ------------------------------------------------------------------------ report

FINDING_HEADING = re.compile(
    r"^(?:#{1,6}\s+|[-+*]\s+|\d+[.)]\s+)"
    r"(?:(?:\*\*|__)?\[?(P[0-3])(?=\]|\s|:|—|–|-\s)\]?"
    r"|(?:\*\*|__)?\[(Critical|High|Medium|Low)\]"
    r"|(?:\*\*|__)(Critical|High|Medium|Low)(?=\s+[—–]|:))",
    re.I,
)
ZERO_MARKER = re.compile(r"^(?:\*\*|__)?\s*:\s*(?:0|none|n/?a)\s*(?:\*\*|__)?\s*\.?\s*$", re.I)
CONTAINER_TITLE = re.compile(r"^(?:findings?|items?|issues?)\s*\(?\d*\)?[:.]?$", re.I)
SEVERITY_WORDS = {"critical": "P0", "high": "P1", "medium": "P2", "low": "P3"}
VERDICT_LINE = re.compile(r"VERDICT: (PASS|PASS WITH NOTES|FAIL)")
TAG_START = re.compile(r"FINDINGS\s*:")
TAG_FULL = re.compile(r"FINDINGS: (\d+) \(P0: (\d+), P1: (\d+), P2: (\d+)(?:, P3: (\d+))?\)")
ATX = re.compile(r"^#{1,6}\s")
LEAD_MARKERS = re.compile(r"^(?:>\s*)*(?:#{1,6}\s+|[-+*]\s+|\d+[.)]\s+)?")
CANDIDATE_P = re.compile(r"^P\d+(?=$|[\s:\]*_—–]|-[\d\s])", re.I)
CANDIDATE_WORD = re.compile(r"^(?:Critical|High|Medium|Low)(?:\s*:|\s+[-–—](?:\s|$)|\]|\*\*|__|$)", re.I)
TABLE_CELL = re.compile(r"(?:P\d+|critical|high|medium|low)", re.I)
LOCATION = re.compile(r"(?<![A-Za-z0-9_./-])[A-Za-z0-9_./-]+:[1-9][0-9]*(?:-[1-9][0-9]*)?(?![A-Za-z0-9_./-])")


def _is_candidate(stripped: str) -> bool:
    lead = LEAD_MARKERS.sub("", stripped, count=1)
    lead = re.sub(r"^(?:\*\*|__)*\[?", "", lead)
    return bool(CANDIDATE_P.match(lead) or CANDIDATE_WORD.match(lead))


def _table_candidate(stripped: str) -> bool:
    for cell in stripped.strip("|").split("|"):
        core = re.sub(r"[\s*_\[\]]", "", cell)
        if core and TABLE_CELL.fullmatch(core):
            return True
    return False


def parse_report(raw: bytes) -> dict:
    """Validate the report grammar and extract findings. Exit 13 for anything unsupported."""

    def fail(reason: str) -> NoReturn:
        raise ImportFailure(EXIT_REPORT, reason)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        fail("report is not valid UTF-8")
    try:
        # An escaped credential in report prose is still a recoverable credential.
        text = helpers()["scanner"].unescape_text(text)
    except ImportFailure:
        raise
    except Exception as exc:
        raise ImportFailure(EXIT_SCRUB, "report decode fault") from exc
    if not text.strip():
        fail("report is empty")
    if "\x00" in text or "```" in text or "~~~" in text or "<!--" in text or "-->" in text:
        fail("report contains a fence, comment or NUL")
    text = text.replace("\r\n", "\n")
    if "\r" in text:
        fail("report contains a lone carriage return")
    lines = text.split("\n")
    last = max(index for index, line in enumerate(lines) if line.strip())
    match = VERDICT_LINE.fullmatch(lines[last])
    if match is None:
        fail("report does not end with a verdict line")
    if last > 0 and lines[last - 1].strip():
        fail("verdict line must follow a blank line")
    for index, line in enumerate(lines):
        if index != last and line.strip().startswith("VERDICT:"):
            fail("duplicate verdict line")
    verdict = match.group(1)

    tag_lines = [index for index in range(last) if TAG_START.match(lines[index].strip())]
    if len(tag_lines) > 1:
        fail("duplicate FINDINGS line")
    findings: list[dict] = []
    counts = None
    method = "none"
    if tag_lines:
        tag = TAG_FULL.fullmatch(lines[tag_lines[0]].strip())
        if tag is None:
            fail("malformed FINDINGS line")
        counts = [int(tag.group(n) or 0) for n in range(2, 6)]
        total = int(tag.group(1))
        if total != sum(counts):
            fail("FINDINGS total does not match its breakdown")
        method = "receipt-headings-v2"
        findings = _classify(lines, last, tag_lines[0], fail)
        got = [sum(1 for f in findings if f["severity"] == f"P{n}") for n in range(4)]
        if got != counts:
            fail("FINDINGS counts do not match the extracted findings")
    return {"lines": lines, "last": last, "verdict": verdict, "method": method, "findings": findings, "text": text}


def _classify(lines: list[str], last: int, tag_index: int, fail) -> list[dict]:
    kinds: dict[int, str] = {}
    found: dict[int, dict] = {}
    for index in range(last):
        stripped = lines[index].strip()
        if not stripped or index == tag_index:
            continue
        if stripped.startswith("|"):
            if _table_candidate(stripped):
                fail("table rows are not supported")
            continue
        match = FINDING_HEADING.match(stripped)
        if match is None:
            if _is_candidate(stripped):
                fail("unsupported finding heading")
            continue
        rest = stripped[match.end():]
        if ZERO_MARKER.match(rest):
            kinds[index] = "zero"
            continue
        word = match.group(1) or match.group(2) or match.group(3)
        severity = word.upper() if word.upper().startswith("P") and word[1:].isdigit() else SEVERITY_WORDS[word.lower()]
        title = re.sub(r"^[:\-–—\]]+\s*", "", rest.lstrip()).strip()
        if not title or CONTAINER_TITLE.fullmatch(title):
            following = next((lines[j].strip() for j in range(index + 1, last) if lines[j].strip()), "")
            if ATX.match(stripped) and following and FINDING_HEADING.match(following):
                kinds[index] = "container"
                continue
            fail("empty or noun-only finding title")
        kinds[index] = "finding"
        found[index] = {"index": index, "severity": severity, "title": title}
    boundaries = sorted(set(kinds) | {tag_index} | {i for i in range(last) if ATX.match(lines[i].strip())})
    findings: list[dict] = []
    for index in sorted(found):
        end = next((b for b in boundaries if b > index), last)
        while end - 1 > index and not lines[end - 1].strip():
            end -= 1
        item = found[index]
        item["start"] = index
        item["end"] = end
        findings.append(item)
    return findings


# ----------------------------------------------------------------------- derivatives


def find_location(text: str) -> str:
    match = LOCATION.search(text)
    return match.group(0) if match else ""


INDEX_ESCAPES = str.maketrans(
    {"&": "&amp;", '"': "&quot;", "|": "&#124;", "#": "&#35;", "<": "&lt;", ">": "&gt;"}
)


def escape_index(value: str) -> str:
    # One simultaneous pass: a sequential replace would re-escape earlier entities.
    return re.sub(r"[\r\n\t]+", " ", value.translate(INDEX_ESCAPES))


def build_rows(parsed: dict, bundle: str, receipt: dict) -> list[dict]:
    lines = parsed["lines"]
    agent = f"fd-external-review-{bundle}"
    reviewer = scrub(receipt["reviewer_identity"])
    producer = scrub(receipt["producer_identity"])
    rows = []
    for item in parsed["findings"]:
        start, end = item["start"], item["end"]
        block = "\n".join(line.rstrip() for line in lines[start:end])
        scrubbed_block = scrub(block)
        location = find_location(block)
        if find_location(scrubbed_block) != location:
            raise ImportFailure(EXIT_SCRUB, "scrubbing changed a cited location")
        continuation = [line.rstrip() for line in lines[start + 1 : end] if line.strip()][:2]
        excerpt = "\n".join([lines[start].rstrip()] + continuation)
        # Scrub the whole block before cutting the excerpt, so a multi-line secret
        # (a PEM block) cannot be split into an unrecognisable fragment.
        scrubbed_lines = scrubbed_block.split("\n")
        scrubbed_cont = [line.rstrip() for line in scrubbed_lines[1:] if line.strip()][:2]
        scrubbed_excerpt = scrub("\n".join([scrubbed_lines[0].rstrip()] + scrubbed_cont))
        title = scrub(sanitize(scrub(item["title"])))
        claim = scrub(sanitize(scrubbed_excerpt))
        if not title.strip() or not claim.strip():
            raise ImportFailure(EXIT_REPORT, "sanitization removed a whole title or finding")
        rows.append(
            {
                "id": f"EXT-{start + 1}",
                "severity": item["severity"],
                "title": title,
                "location": location,
                "location_kind": "cited" if location else "none",
                "claim": claim,
                "excerpt": claim,
                "status": "raw",
                "taste": 0,
                "taste_kind": None,
                "line_start": start + 1,
                "line_end": end,
                "source": {
                    "kind": "lens",
                    "agents": [agent],
                    "import": {
                        "bundle_id": bundle,
                        "reviewer_identity": reviewer,
                        "producer_identity": producer,
                        "evidence_class": "external-review",
                        "verification": "unverified",
                        "original_excerpt_sha256": sha256_hex(excerpt.encode("utf-8")),
                        "scrubbed_excerpt_sha256": sha256_hex(scrubbed_excerpt.encode("utf-8")),
                        "claim_sha256": sha256_hex(claim.encode("utf-8")),
                        "location_kind": "cited" if location else "none",
                    },
                },
            }
        )
    return rows


def build_index(rows: list[dict], bundle: str, reviewer: str, producer: str, verdict: str) -> str:
    out = [
        f"# External review import {bundle}",
        "",
        "Findings below come from a separately packaged review. They are raw and unverified.",
        f"Reviewer: {escape_index(reviewer)}. Producer: {escape_index(producer)}.",
        "",
        "## Findings Index",
    ]
    for row in rows:
        section = escape_index(row["location"]) if row["location"] else "External review"
        out.append(f'- {row["severity"]} | {row["id"]} | "{section}" | {escape_index(row["title"])}')
    out += ["", "## Verdict", f"Imported report verdict: {verdict} (unverified external evidence).", ""]
    return "\n".join(out)


def build_files(receipt: dict, receipt_sha: str, report_sha: str, parsed: dict, bundle: str, labs: tuple[str, str]) -> dict[str, bytes]:
    rows = build_rows(parsed, bundle, receipt)
    reviewer_lab, producer_lab = labs
    manifest = {
        "schema": "melange-import-v3",
        "bundle_id": bundle,
        "receipt_sha256": receipt_sha,
        "report_sha256": report_sha,
        "provenance": {
            "reviewer_identity": receipt["reviewer_identity"],
            "producer_identity": receipt["producer_identity"],
            "reviewer_lab": reviewer_lab,
            "producer_lab": producer_lab,
            "dispatch_id": receipt["dispatch_id"],
            "reviewer_effort": NOT_IN_RECEIPT,
            "reviewer_runtime": NOT_IN_RECEIPT,
        },
        "binding": {
            "label": BINDING_LABEL,
            "operator_hash_check": "matched",
            "target_check": "not-performed",
            "applicability_note": APPLICABILITY_NOTE,
        },
        "extraction": {"method": parsed["method"], "finding_count": len(rows)},
        "imported_as": {
            "findings": "findings.jsonl rows, raw and unverified",
            "external_evidence": ["external-evidence/receipt.redacted.json", "external-evidence/report.redacted.md"],
        },
    }
    index_text = scrub(build_index(rows, bundle, receipt["reviewer_identity"], receipt["producer_identity"], parsed["verdict"]))
    jsonl = b"".join(canonical_scrubbed(row) for row in rows)
    return {
        "manifest.json": canonical_scrubbed(manifest),
        "findings.jsonl": jsonl,
        f"findings/fd-external-review-{bundle}.md": index_text.encode("utf-8"),
        "external-evidence/receipt.redacted.json": canonical_scrubbed(receipt),
        "external-evidence/report.redacted.md": scrub(parsed["text"]).encode("utf-8"),
    }


# --------------------------------------------------------------------------- scan


def scan_binary():
    scanner = helpers()["scanner"]
    try:
        binary = scanner.locate_gitleaks()
        scanner.check_gitleaks(binary)
        scanner.config_path()
    except scanner.ScannerFailure as exc:
        raise ImportFailure(EXIT_SCANNER, "gitleaks is unavailable") from exc
    return binary


def scan_bytes(binary: str, items: dict[str, bytes]) -> None:
    """Exit 20 when any file carries residue, 22 when the scan could not complete."""
    scanner = helpers()["scanner"]
    genuine = helpers()["hook"].scrub
    residue = False
    failed = False
    for name in sorted(items):
        found, broke = scanner.bytes_have_residue(genuine, binary, items[name], os.path.basename(name))
        residue = residue or found
        failed = failed or broke
    if residue:
        raise ImportFailure(EXIT_RESIDUE)
    if failed:
        raise ImportFailure(EXIT_SCANNER)


# ------------------------------------------------------------------------ publish


def late_import(run_fd: int) -> bool:
    """True when the run is past the point where a new bundle can be assimilated. Reads through the pinned run descriptor."""
    try:
        with os.scandir(run_fd) as listing:
            names = [entry.name for entry in listing]
    except OSError as exc:
        raise ImportFailure(EXIT_RUN) from exc
    if any(name.endswith("-synthesis.md") or name == "surfaced.jsonl" for name in names):
        return True
    try:
        fd = os.open("melange-state.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=run_fd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ImportFailure(EXIT_RUN)
            with os.fdopen(fd, "rb", closefd=False) as handle:
                state = json.loads(handle.read().decode("utf-8"))
        finally:
            os.close(fd)
    except (OSError, ValueError) as exc:
        raise ImportFailure(EXIT_RUN) from exc
    return isinstance(state, dict) and "import_assimilation" in state


def _walk_bundle(bundle_fd: int) -> dict[str, bytes]:
    scanner = helpers()["scanner"]
    try:
        return dict(scanner.walk_files(None, root_fd=bundle_fd))
    except scanner.ScannerFailure as exc:
        raise ImportFailure(EXIT_CONFLICT) from exc


def _open_dir(name: str, dir_fd: int | None = None) -> int:
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)


def revalidate_existing(imports_fd: int, bundle: str, expected: dict[str, bytes], binary: str) -> None:
    """An existing bundle is accepted only when it scans clean and equals the fresh build."""
    try:
        bundle_fd = _open_dir(bundle, imports_fd)
    except OSError as exc:
        raise ImportFailure(EXIT_CONFLICT) from exc
    try:
        present = _walk_bundle(bundle_fd)
    finally:
        os.close(bundle_fd)
    scan_bytes(binary, present)
    if present != expected:
        raise ImportFailure(EXIT_CONFLICT, "existing bundle differs from the fresh build")


def git_ignores(project: Path, relative: str) -> bool:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        proc = subprocess.run(
            ["git", "-C", str(project), "check-ignore", "-q", "--", relative],
            capture_output=True,
            timeout=30,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _renameat2(source_fd: int, source: str, target_fd: int, target: str) -> None:
    """Move without replacing: renameat2 with RENAME_NOREPLACE, relative to pinned directories. Any failure is an OSError."""
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, "renameat2", None)
    if fn is None:
        raise OSError(errno.ENOSYS, os.strerror(errno.ENOSYS))
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    if fn(source_fd, os.fsencode(source), target_fd, os.fsencode(target), RENAME_NOREPLACE) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def _pin(path: Path) -> int:
    """Open a directory without following a final symlink and confirm it is the entry that was inspected."""
    info = os.lstat(path)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    got = os.fstat(fd)
    if (got.st_dev, got.st_ino) != (info.st_dev, info.st_ino):
        os.close(fd)
        raise ImportFailure(EXIT_CONFLICT, "directory replaced while it was being pinned")
    return fd


def _ensure_dir_at(parent_fd: int, name: str) -> int:
    """Create (mode 0700) or open a directory under a pinned parent; it must be ours."""
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    fd = _open_dir(name, parent_fd)
    if os.fstat(fd).st_uid != os.getuid():
        os.close(fd)
        raise ImportFailure(EXIT_CONFLICT)
    return fd


def _write_file_at(dir_fd: int, name: str, data: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def other_bundles(imports_fd: int, bundle: str) -> bool:
    """True when imports/ holds anything besides this bundle: a second distinct import is refused."""
    try:
        with os.scandir(imports_fd) as listing:
            return any(entry.name != bundle for entry in listing)
    except OSError as exc:
        raise ImportFailure(EXIT_CONFLICT) from exc


def _take_back(imports_fd: int, bundle: str, staging_fd: int) -> str | None:
    """Move a published bundle back to staging. Returns the staging name to clean up, or raises exit 21 when it cannot be removed."""
    rollback = f"rollback-{secrets.token_hex(8)}"
    try:
        _renameat2(imports_fd, bundle, staging_fd, rollback)
        return rollback
    except OSError:
        pass
    try:
        shutil.rmtree(bundle, dir_fd=imports_fd)
        return None
    except OSError:
        pass
    raise ImportFailure(EXIT_CONFLICT, "the published bundle could not be removed; delete it before assimilating")


def publish(run: Path, project: Path, bundle: str, files: dict[str, bytes], binary: str) -> None:
    """Publish the bundle through pinned directory descriptors.

    The run, the project root, the staging directory and imports/ are each opened once and
    every later step is relative to those descriptors, so replacing a path component with a
    symlink after the checks cannot redirect the write or the rename. The late check runs
    before staging and again after the rename: an assimilation that began in between rolls
    the new bundle back (exit 16) instead of leaving a bundle the snapshot may have missed.
    """
    relative = "/".join(STAGING_RELATIVE) + "/.lock"
    if not git_ignores(project, relative):
        raise ImportFailure(EXIT_CONFLICT, "staging directory is not git-ignored")
    open_fds: list[int] = []

    def keep(fd: int) -> int:
        open_fds.append(fd)
        return fd

    staging_fd = -1
    work_name: str | None = None
    try:
        try:
            run_fd = keep(_pin(run))
            parent = keep(_pin(project))
            for component in STAGING_RELATIVE:
                parent = keep(_ensure_dir_at(parent, component))
            staging_fd = parent
            os.fchmod(staging_fd, 0o700)
            imports_fd = keep(_ensure_dir_at(run_fd, "imports"))
            if os.fstat(staging_fd).st_dev != os.fstat(imports_fd).st_dev:
                raise ImportFailure(EXIT_CONFLICT, "staging and imports are on different filesystems")
            lock = keep(os.open(".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=staging_fd))
        except OSError as exc:
            raise ImportFailure(EXIT_CONFLICT) from exc
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ImportFailure(EXIT_CONFLICT, "another import holds the lock") from exc
        try:
            os.lstat(bundle, dir_fd=imports_fd)
            exists = True
        except FileNotFoundError:
            exists = False
        except OSError as exc:
            raise ImportFailure(EXIT_CONFLICT) from exc
        if exists:
            revalidate_existing(imports_fd, bundle, files, binary)
            return
        if late_import(run_fd) or other_bundles(imports_fd, bundle):
            raise ImportFailure(EXIT_LATE)
        try:
            work_name = f"{bundle[:16]}-{secrets.token_hex(8)}"
            os.mkdir(work_name, 0o700, dir_fd=staging_fd)
            work_fd = keep(_open_dir(work_name, staging_fd))
            for name, data in sorted(files.items()):
                *directories, leaf = name.split("/")
                target = work_fd
                for part in directories:
                    target = keep(_ensure_dir_at(target, part))
                _write_file_at(target, leaf, data)
            _renameat2(staging_fd, work_name, imports_fd, bundle)
            work_name = None
        except OSError as exc:
            raise ImportFailure(EXIT_CONFLICT, "could not publish the bundle") from exc
        # The bundle is visible now. Any failure from here on must take it back out, so that
        # no admissible bundle is left that an assimilation snapshot may have missed.
        try:
            if late_import(run_fd):
                raise ImportFailure(EXIT_LATE)
        except BaseException:
            work_name = _take_back(imports_fd, bundle, staging_fd)
            raise
    finally:
        if work_name is not None and staging_fd >= 0:
            try:
                shutil.rmtree(work_name, dir_fd=staging_fd)
            except OSError:
                pass
        for fd in reversed(open_fds):
            try:
                os.close(fd)
            except OSError:
                pass


# -------------------------------------------------------------------------- main


def run_import(argv: list[str]) -> str:
    args = parse_args(argv)
    receipt_arg, report_arg = args["--receipt"], args["--report"]
    precheck_input(receipt_arg)
    precheck_input(report_arg)
    check_path_text(args["--run-dir"])
    run, project = validate_run(args["--run-dir"])

    receipt_bytes = read_input(receipt_arg, RECEIPT_CAP, missing=EXIT_RECEIPT, oversize=EXIT_RECEIPT, ioerr=EXIT_RECEIPT)
    receipt = validate_receipt(receipt_bytes)
    if os.path.basename(receipt_arg) != receipt_basename(receipt):
        raise ImportFailure(EXIT_RECEIPT, "receipt file name does not match its contents")
    report_bytes = read_input(report_arg, REPORT_CAP, missing=EXIT_IO, oversize=EXIT_REPORT, ioerr=EXIT_IO)
    report_sha = sha256_hex(report_bytes)
    if report_sha != args["--report-sha256"]:
        raise ImportFailure(EXIT_HASH)
    labs = admit_labs(receipt)
    parsed = parse_report(report_bytes)
    receipt_verdict = receipt["verdict"]
    agrees = (
        (parsed["verdict"] in ("PASS", "PASS WITH NOTES") and receipt_verdict in ("PASS", "PASS WITH NOTES"))
        or (parsed["verdict"] == "FAIL" and receipt_verdict == "BLOCK")
    )
    if not agrees:
        raise ImportFailure(EXIT_VERDICT)

    receipt_sha = sha256_hex(receipt_bytes)
    bundle = sha256_hex(BUNDLE_SCHEMA + receipt_sha.encode() + b"\0" + report_sha.encode())
    helpers()
    files = build_files(receipt, receipt_sha, report_sha, parsed, bundle, labs)
    binary = scan_binary()
    scan_bytes(binary, files)

    publish(run, project, bundle, files, binary)
    return bundle


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        bundle = run_import(args)
    except ImportFailure as failure:
        print(f"import failed (exit {failure.code}): {failure.reason}", file=sys.stderr)
        return failure.code
    except OSError:
        print(f"import failed (exit {EXIT_IO}): {MESSAGES[EXIT_IO]}", file=sys.stderr)
        return EXIT_IO
    except Exception:
        # Never echo exception text; it can carry report content.
        print(f"import failed (exit {EXIT_SCRUB}): {MESSAGES[EXIT_SCRUB]}", file=sys.stderr)
        return EXIT_SCRUB
    print(f"imported {bundle}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
