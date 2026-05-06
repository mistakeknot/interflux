"""Per-run decisions log — JSONL audit trail for orchestration decisions.

A flux-drive run makes many decisions before any agent dispatches: which agents
the triage selected, which the AgentDropout step culled, which the expansion
rule promoted to Stage 2, which budget cuts kicked in. None of these were
recorded; debugging "why didn't fd-X run?" required re-reading the orchestrator
transcript.

This module provides a thin write helper that appends decision records to
`{OUTPUT_DIR}/decisions.log` (JSONL, one record per line). Records reuse the
VerificationStep schema from `_verification.py` so the audit format is
coherent across orchestrator decisions and per-state-transition checks.

Public API:

    log_decision(name, evidence, *, decision_type=None, output_dir=None, **extra)
        Append a decision record. If output_dir is None, falls back to
        $FLUX_OUTPUT_DIR. Silently no-ops if neither is set (so callers can
        invoke this unconditionally without checking context).

    get_log_path(output_dir) -> str
        Returns the canonical decisions.log path for an output dir.

    read_log(output_dir) -> list[dict]
        Parses decisions.log for inspection (testing + post-mortem).

CLI (used from shell phase files):
    python3 -m _decisions_log log <name> <evidence>
        [--decision-type=X] [--extra-json='{...}'] [--output-dir=PATH]

The CLI reads $FLUX_OUTPUT_DIR if --output-dir is not passed.

Schema (per record):
    name           — kebab-case identifier (e.g., 'triage-rank', 'budget-cut')
    state          — VERIFIED (decisions are recorded after the fact)
    evidence       — human-readable description
    decision_type  — 'triage' | 'expansion' | 'dropout' | 'budget' | <custom>
    run_uuid       — auto-populated from $FLUX_RUN_UUID
    timestamp_ms   — auto-populated
    step_id        — auto-populated uuid4
    extra          — caller-supplied JSON-serializable extras (scores, slugs, ...)

See scripts/README.md § Decisions log for the canonical decision_type values
and recommended integration sites.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# scripts/ is on the path when this is run via 'python3 -m _decisions_log'
# from the plugin root or 'python3 scripts/_decisions_log.py' invocation.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _verification import VerificationState, VerificationStep, append_to_log  # noqa: E402


LOG_FILENAME = "decisions.log"


def get_log_path(output_dir: str) -> str:
    """Canonical decisions.log path for a given OUTPUT_DIR."""
    return os.path.join(output_dir, LOG_FILENAME)


def log_decision(
    name: str,
    evidence: str,
    *,
    decision_type: str | None = None,
    output_dir: str | None = None,
    **extra: Any,
) -> bool:
    """Append a decision record. Returns True if written, False if no-op.

    No-op (returns False) when neither `output_dir` nor `$FLUX_OUTPUT_DIR` is
    set — lets callers invoke unconditionally from contexts where the run
    directory isn't established yet (e.g., during early bootstrap).
    """
    target_dir = output_dir or os.environ.get("FLUX_OUTPUT_DIR")
    if not target_dir:
        return False
    if not os.path.isdir(target_dir):
        # Don't auto-create — if OUTPUT_DIR is misspelled, silent log creation
        # would mask the bug. Caller is expected to mkdir during Phase 2.0.
        return False
    # Construct directly rather than via .verified(**extra) — the factory
    # interprets **extra kwargs as extras-dict keys, but we already have
    # `extra` as a dict; passing it via kwarg expansion would be the right
    # call but `decision_type` and `run_uuid` collide with VerificationStep
    # named fields. Direct construction is clearer.
    step = VerificationStep(
        name=name,
        state=VerificationState.VERIFIED,
        evidence=evidence,
        decision_type=decision_type,
        extra=dict(extra) if extra else {},
    )
    append_to_log(step, get_log_path(target_dir))
    return True


def read_log(output_dir: str) -> list[dict[str, Any]]:
    """Parse decisions.log into a list of dict records. Returns [] if missing."""
    path = get_log_path(output_dir)
    if not os.path.isfile(path):
        return []
    records: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed lines — robust to partial writes during dev.
                continue
    return records


# --- CLI ------------------------------------------------------------------


def _cli_log(args: argparse.Namespace) -> int:
    extras: dict[str, Any] = {}
    if args.extra_json:
        try:
            parsed = json.loads(args.extra_json)
        except json.JSONDecodeError as exc:
            print(f"_decisions_log: invalid --extra-json: {exc}", file=sys.stderr)
            return 4
        if not isinstance(parsed, dict):
            print(f"_decisions_log: --extra-json must be an object", file=sys.stderr)
            return 4
        extras = parsed

    written = log_decision(
        args.name,
        args.evidence,
        decision_type=args.decision_type,
        output_dir=args.output_dir,
        **extras,
    )
    if not written:
        # No-op exit code 0 — callers shouldn't fail just because the run
        # directory isn't ready yet (early bootstrap, dry-run, etc.).
        if args.verbose:
            print("_decisions_log: no FLUX_OUTPUT_DIR set; skipping", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="_decisions_log",
        description="Append decision records to a per-run JSONL log.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    log_p = sub.add_parser("log", help="Append a single decision record")
    log_p.add_argument("name")
    log_p.add_argument("evidence")
    log_p.add_argument("--decision-type", default=None)
    log_p.add_argument("--extra-json", default=None,
                       help="JSON object string to merge into the 'extra' field")
    log_p.add_argument("--output-dir", default=None,
                       help="Override $FLUX_OUTPUT_DIR for this call")
    log_p.add_argument("-v", "--verbose", action="store_true")
    log_p.set_defaults(func=_cli_log)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
