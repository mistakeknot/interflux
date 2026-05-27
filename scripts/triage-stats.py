#!/usr/bin/env python3
"""Analyze triage.jsonl to report per-agent skip rates and scoring contributions.

Reads .clavain/interflux/triage.jsonl (schema v1, see
Sylveste/docs/contracts/triage-log-schema.md) and emits a per-agent
summary table:

  Agent              Runs  Selected  Skip%  Avg final  Avg q_signal
  fd-architecture    142   141       0.7%   6.4        +0.12
  fd-correctness     142   89        37.3%  3.1        -0.42

The Skip% and Avg q_signal columns tell you whether interspect's
quality_signal_adjust is causing meaningful skip decisions or is
contributing 0 across the board (i.e. cold-start mode).

Usage:
  triage-stats.py [--days=30] [--input-stem=...] [--repo-root=.]
                  [--min-runs=5] [--json]

Examples:
  # Default 30-day summary, human-readable
  triage-stats.py

  # Same data as JSON, for piping
  triage-stats.py --json

  # Recent triages only
  triage-stats.py --days=7

  # Filter to triages of a specific target
  triage-stats.py --input-stem=auth-refactor
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean


def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    while p != p.parent:
        if (p / ".clavain").exists() or (p / ".git").exists():
            return p
        p = p.parent
    return start.resolve()


def parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def stream_entries(path: Path, cutoff: datetime, input_stem: str | None):
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = parse_iso(e.get("ts", ""))
                if not ts or ts < cutoff:
                    continue
                if input_stem and e.get("input_stem") != input_stem:
                    continue
                yield e
    except OSError:
        return


def summarize(entries) -> dict[str, dict]:
    """Aggregate per-agent stats."""
    by_agent: dict[str, dict] = defaultdict(
        lambda: {
            "runs": 0,
            "selected": 0,
            "final_scores": [],
            "quality_signal_adjusts": [],
            "skip_reasons": defaultdict(int),
        }
    )
    runs_seen: set[str] = set()
    for e in entries:
        agent = e.get("agent")
        if not agent:
            continue
        run_id = e.get("run_id", "")
        if run_id:
            runs_seen.add(run_id)
        stats = by_agent[agent]
        stats["runs"] += 1
        if e.get("selected"):
            stats["selected"] += 1
        if isinstance(e.get("final_score"), (int, float)):
            stats["final_scores"].append(float(e["final_score"]))
        if isinstance(e.get("quality_signal_adjust"), (int, float)):
            stats["quality_signal_adjusts"].append(float(e["quality_signal_adjust"]))
        reason = e.get("skip_reason") or ""
        if reason:
            # Coarse-grain the reason for histogram purposes.
            key = reason.split(":")[0].split(" 0")[0].strip()[:60]
            stats["skip_reasons"][key] += 1
    return by_agent, runs_seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--input-stem", default="")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--min-runs", type=int, default=1)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    repo_root = find_repo_root(Path(args.repo_root))
    log_path = repo_root / ".clavain" / "interflux" / "triage.jsonl"

    if not log_path.exists():
        print(
            f"triage-stats: no log at {log_path}. "
            "Run flux-engine at least once with the triage-log instructions "
            "(see SKILL.md Step 1.2b).",
            file=sys.stderr,
        )
        return 1

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    entries = list(stream_entries(log_path, cutoff, args.input_stem or None))
    if not entries:
        print(
            f"triage-stats: no entries in {log_path} within --days={args.days}"
            + (f" --input-stem={args.input_stem}" if args.input_stem else ""),
            file=sys.stderr,
        )
        return 0

    by_agent, runs_seen = summarize(entries)
    total_runs = len(runs_seen)

    rows = []
    for agent, stats in by_agent.items():
        if stats["runs"] < args.min_runs:
            continue
        selected = stats["selected"]
        runs = stats["runs"]
        skip_rate = 1 - (selected / runs) if runs else 0
        avg_final = mean(stats["final_scores"]) if stats["final_scores"] else 0
        avg_qsa = (
            mean(stats["quality_signal_adjusts"])
            if stats["quality_signal_adjusts"]
            else 0
        )
        rows.append(
            {
                "agent": agent,
                "runs": runs,
                "selected": selected,
                "skip_rate": round(skip_rate, 3),
                "avg_final_score": round(avg_final, 2),
                "avg_quality_signal_adjust": round(avg_qsa, 3),
                "top_skip_reasons": sorted(
                    stats["skip_reasons"].items(), key=lambda kv: -kv[1]
                )[:3],
            }
        )

    rows.sort(key=lambda r: -r["runs"])

    if args.json:
        print(
            json.dumps(
                {
                    "window_days": args.days,
                    "input_stem_filter": args.input_stem or None,
                    "total_runs": total_runs,
                    "agents": rows,
                }
            )
        )
        return 0

    print(
        f"triage-stats: {total_runs} triages over the last {args.days} days"
        + (f" (filter: input_stem={args.input_stem})" if args.input_stem else "")
    )
    print()
    print(
        f"{'Agent':<24} {'Runs':>5} {'Selected':>8} {'Skip%':>6} "
        f"{'AvgFinal':>9} {'AvgQSA':>7}"
    )
    print("-" * 70)
    for r in rows:
        print(
            f"{r['agent']:<24} "
            f"{r['runs']:>5} "
            f"{r['selected']:>8} "
            f"{r['skip_rate'] * 100:>5.1f}% "
            f"{r['avg_final_score']:>9.2f} "
            f"{r['avg_quality_signal_adjust']:>+7.3f}"
        )

    # Surface notable skip reasons
    print()
    print("Top skip reasons by agent (where skip rate >= 30%):")
    any_shown = False
    for r in rows:
        if r["skip_rate"] < 0.3:
            continue
        if not r["top_skip_reasons"]:
            continue
        any_shown = True
        reasons = ", ".join(
            f"{reason} ({count})" for reason, count in r["top_skip_reasons"]
        )
        print(f"  {r['agent']}: {reasons}")
    if not any_shown:
        print("  (none)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
