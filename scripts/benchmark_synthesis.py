#!/usr/bin/env python3
"""benchmark_synthesis.py — A/B compare subagent synthesis vs teams synthesis.

Runs both synthesis paths on the same spec corpus, then asks a Sonnet reviewer to score
them with anti-position-bias double-run (labels swapped between runs). Writes a
comparison report.

This is the F6 empirical signal that decides whether `--teams` ships as default — the
PRD's acceptance criterion is "measurement happened", not "teams won". A subagent-wins
or tie verdict still closes the bead.

Architecture: this script does NOT actually invoke the subagent or teams synthesis —
those require a Claude Code session context (subagent dispatch, agent-team spawn). It
takes pre-existing synthesis outputs as input (paths to two markdown files) and produces
the reviewer comparison + verdict. The slash-command-level orchestration that runs the
two syntheses lives in a /interflux:flux-explore-bench command (future work — bead-tracked
as part of F6.2 wiring).

CLI:
    python3 benchmark_synthesis.py compare \\
        --subagent-synthesis path/to/A.md \\
        --teams-synthesis path/to/B.md \\
        --slug name \\
        --output docs/research/flux-explore-teams-benchmarks/{slug}/{date}-comparison.md \\
        [--subagent-tokens N] [--teams-tokens N] [--no-llm-review]

Without `--no-llm-review`, the script asks the user (the agent running it) to perform
the rubric scoring twice (labels swapped) by emitting a structured prompt to stdout —
the calling slash command captures the response and writes it back via:

    python3 benchmark_synthesis.py write-report --slug name --output ... \\
        --review-run-1 review1.json --review-run-2 review2.json \\
        --subagent-tokens N --teams-tokens N

This split lets the LLM scoring happen in the slash-command flow (where Sonnet is
available) while the I/O and verdict logic stays in Python.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Any


def _count_isomorphism_sections(content: str) -> int:
    """Count `## Cross-Domain Isomorphism N:` headings (any case)."""
    return sum(
        1
        for line in content.splitlines()
        if line.strip().lower().startswith("## cross-domain isomorphism")
        or line.strip().lower().startswith("# cross-domain isomorphism")
    )


def _has_unresolved_section(content: str) -> bool:
    return any(
        line.strip().lower().startswith("## unresolved tensions")
        or line.strip().lower().startswith("# unresolved tensions")
        for line in content.splitlines()
    )


def _isomorphism_titles(content: str) -> list[str]:
    """Extract titles of `## Cross-Domain Isomorphism N: TITLE` sections."""
    pattern = re.compile(r"^##?\s*cross-domain isomorphism\s*\d*:?\s*(.*)$", re.IGNORECASE)
    titles = []
    for line in content.splitlines():
        m = pattern.match(line.strip())
        if m and m.group(1).strip():
            titles.append(m.group(1).strip())
    return titles


def _structural_score(content: str) -> dict[str, Any]:
    """Pure structural score (no LLM). Counts sections + checks required structure.

    This is the Python-side rubric that runs without an LLM. The full rubric (semantic
    quality of mappings, depth of mechanism description, etc.) requires the Sonnet
    reviewer in the next step.
    """
    isom_count = _count_isomorphism_sections(content)
    has_unresolved = _has_unresolved_section(content)
    titles = _isomorphism_titles(content)
    word_count = len(content.split())
    return {
        "isomorphism_section_count": isom_count,
        "has_unresolved_tensions": has_unresolved,
        "isomorphism_titles": titles,
        "word_count": word_count,
    }


def cmd_emit_review_prompts(args: argparse.Namespace) -> int:
    """Emit two reviewer prompts (labels swapped) for the calling slash command to dispatch."""
    sub_path = Path(args.subagent_synthesis)
    teams_path = Path(args.teams_synthesis)
    if not sub_path.exists():
        print(json.dumps({"error": f"subagent synthesis not at {sub_path}"}))
        return 1
    if not teams_path.exists():
        print(json.dumps({"error": f"teams synthesis not at {teams_path}"}))
        return 1

    sub_content = sub_path.read_text()
    teams_content = teams_path.read_text()
    sub_struct = _structural_score(sub_content)
    teams_struct = _structural_score(teams_content)

    rubric = """Score the two synthesis documents (A and B) using this rubric. Return ONLY a JSON object.

For each document independently:
  - distinct_isomorphisms: count of named, non-redundant cross-domain isomorphisms
  - two_domain_supported: count of isomorphisms with two named source domains AND a named mechanism per domain
  - unresolved_tensions_present: boolean
  - unresolved_tensions_quality: int 1-5 (1=none, 5=concrete contradictions named)
  - unique_isomorphisms_vs_other: list of isomorphism titles present in this doc but NOT in the other

Then a single field:
  - verdict: "A-wins" | "B-wins" | "tie" — based on the combined signals (more distinct isomorphisms, better two-domain support, deeper unresolved-tensions content all favor a doc).

Return JSON: {"a": {...}, "b": {...}, "verdict": "..."}"""

    run1_prompt = f"""# Run 1: A=subagent, B=teams

{rubric}

## Document A:
{sub_content}

## Document B:
{teams_content}
"""
    run2_prompt = f"""# Run 2: A=teams, B=subagent (labels SWAPPED)

{rubric}

## Document A:
{teams_content}

## Document B:
{sub_content}
"""

    out_dir = Path(args.prompt_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "review-run1-prompt.md").write_text(run1_prompt)
    (out_dir / "review-run2-prompt.md").write_text(run2_prompt)

    envelope = {
        "status": "prompts_ready",
        "run1_label_map": {"A": "subagent", "B": "teams"},
        "run2_label_map": {"A": "teams", "B": "subagent"},
        "run1_prompt_path": str(out_dir / "review-run1-prompt.md"),
        "run2_prompt_path": str(out_dir / "review-run2-prompt.md"),
        "subagent_structural": sub_struct,
        "teams_structural": teams_struct,
    }
    print(json.dumps(envelope, indent=2))
    return 0


def _normalize_verdict(verdict_str: str, label_map: dict[str, str]) -> str:
    """Translate a verdict from A/B labels to subagent/teams labels using the map."""
    v = verdict_str.lower().strip()
    if v == "tie":
        return "tie"
    if v.startswith("a-"):
        winner = label_map.get("A", "?").lower()
        return f"{winner}-wins"
    if v.startswith("b-"):
        winner = label_map.get("B", "?").lower()
        return f"{winner}-wins"
    return "inconclusive"


def cmd_write_report(args: argparse.Namespace) -> int:
    """Read the two LLM review JSON outputs (with label maps), aggregate, write report."""
    run1 = json.loads(Path(args.review_run_1).read_text())
    run2 = json.loads(Path(args.review_run_2).read_text())

    run1_map = {"A": "subagent", "B": "teams"}
    run2_map = {"A": "teams", "B": "subagent"}

    v1 = _normalize_verdict(run1.get("verdict", ""), run1_map)
    v2 = _normalize_verdict(run2.get("verdict", ""), run2_map)

    if v1 == v2:
        final_verdict = v1
    else:
        # Disagreement between runs → inconclusive (anti-position-bias safeguard)
        final_verdict = "inconclusive"

    # Aggregate per-side scores from each run
    sub_run1 = run1.get("a", {}) if run1_map["A"] == "subagent" else run1.get("b", {})
    sub_run2 = run2.get("a", {}) if run2_map["A"] == "subagent" else run2.get("b", {})
    teams_run1 = run1.get("a", {}) if run1_map["A"] == "teams" else run1.get("b", {})
    teams_run2 = run2.get("a", {}) if run2_map["A"] == "teams" else run2.get("b", {})

    def avg_int(a: dict, b: dict, key: str) -> float | None:
        va, vb = a.get(key), b.get(key)
        if va is None or vb is None:
            return va if vb is None else vb
        return (va + vb) / 2

    today = _dt.date.today().isoformat()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report = f"""---
artifact_type: benchmark
bead: {args.bead or 'sylveste-3xl3.1.9'}
date: {today}
slug: {args.slug}
verdict: {final_verdict}
run1_verdict: {v1}
run2_verdict: {v2}
subagent_tokens: {args.subagent_tokens}
teams_tokens: {args.teams_tokens}
---

# A/B Benchmark: subagent vs teams synthesis ({args.slug})

## Verdict: **{final_verdict}**

Two reviewer runs with labels swapped (anti-position-bias safeguard). Verdicts:

- Run 1 (A=subagent, B=teams): {v1}
- Run 2 (A=teams, B=subagent): {v2}

When the two runs agree, that is the final verdict. When they disagree, the result is
`inconclusive` — the reviewer's preference is bound to label position, not content.

## Token cost

| Path     | Tokens     |
|----------|------------|
| Subagent | {args.subagent_tokens} |
| Teams    | {args.teams_tokens} |
| Ratio    | {round(args.teams_tokens / max(1, args.subagent_tokens), 2)}x |

The PRD baseline cost is $2.93/landable change. The teams path is acceptable up to 4x
the subagent path; above that, the value lift must be substantial to justify default-on.

## Per-side scores (averaged across the two runs)

| Metric | Subagent | Teams |
|--------|----------|-------|
| distinct_isomorphisms | {avg_int(sub_run1, sub_run2, 'distinct_isomorphisms')} | {avg_int(teams_run1, teams_run2, 'distinct_isomorphisms')} |
| two_domain_supported | {avg_int(sub_run1, sub_run2, 'two_domain_supported')} | {avg_int(teams_run1, teams_run2, 'two_domain_supported')} |
| unresolved_tensions_quality | {avg_int(sub_run1, sub_run2, 'unresolved_tensions_quality')} | {avg_int(teams_run1, teams_run2, 'unresolved_tensions_quality')} |

## Unique isomorphisms

### Only in subagent synthesis
Run 1: {sub_run1.get('unique_isomorphisms_vs_other', [])}
Run 2: {sub_run2.get('unique_isomorphisms_vs_other', [])}

### Only in teams synthesis
Run 1: {teams_run1.get('unique_isomorphisms_vs_other', [])}
Run 2: {teams_run2.get('unique_isomorphisms_vs_other', [])}

## Source documents

- Subagent synthesis: {args.subagent_synthesis or '(not recorded)'}
- Teams synthesis: {args.teams_synthesis or '(not recorded)'}

## Interpretation guide

- `teams-wins` (both runs agreed): consider making `--teams` opt-out (default-on) for
  design brainstorms with synthesis-track. File follow-up bead.
- `subagent-wins` (both runs agreed): keep `--teams` opt-in. File a /clavain:compound
  doc explaining why the experiment failed (likely candidates: anchoring at debater
  level, cluster-distance too coarse, round cap too tight).
- `tie` (both runs agreed on tie): keep `--teams` opt-in; the cost premium is not
  justified by the lift.
- `inconclusive` (runs disagreed): position bias is dominating; rerun with a different
  reviewer model or expand the corpus before drawing conclusions.
"""
    out_path.write_text(report)
    envelope = {
        "status": "report_written",
        "report_path": str(out_path),
        "verdict": final_verdict,
        "run1_verdict": v1,
        "run2_verdict": v2,
    }
    print(json.dumps(envelope, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B benchmark: subagent vs teams synthesis.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_emit = sub.add_parser(
        "emit-review-prompts",
        help="Emit two reviewer prompts (labels swapped) + structural pre-scores",
    )
    p_emit.add_argument("--subagent-synthesis", required=True)
    p_emit.add_argument("--teams-synthesis", required=True)
    p_emit.add_argument(
        "--prompt-dir",
        required=True,
        help="Where to write review-run1-prompt.md and review-run2-prompt.md",
    )
    p_emit.set_defaults(func=cmd_emit_review_prompts)

    p_write = sub.add_parser("write-report", help="Aggregate two LLM review JSONs and write report")
    p_write.add_argument("--review-run-1", required=True)
    p_write.add_argument("--review-run-2", required=True)
    p_write.add_argument("--slug", required=True)
    p_write.add_argument("--output", required=True)
    p_write.add_argument("--subagent-tokens", type=int, default=0)
    p_write.add_argument("--teams-tokens", type=int, default=0)
    p_write.add_argument("--subagent-synthesis", default=None)
    p_write.add_argument("--teams-synthesis", default=None)
    p_write.add_argument("--bead", default=None)
    p_write.set_defaults(func=cmd_write_report)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
