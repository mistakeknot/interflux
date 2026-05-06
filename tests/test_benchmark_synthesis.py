"""Unit tests for benchmark_synthesis.py.

Run: python3 -m pytest interverse/interflux/tests/test_benchmark_synthesis.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from benchmark_synthesis import (  # noqa: E402
    _count_isomorphism_sections,
    _has_unresolved_section,
    _isomorphism_titles,
    _normalize_verdict,
    _structural_score,
)

BENCH = SCRIPT_DIR / "benchmark_synthesis.py"


def test_count_isomorphisms_h2_only():
    content = "## Cross-Domain Isomorphism 1: A\n## Cross-Domain Isomorphism 2: B\n"
    assert _count_isomorphism_sections(content) == 2


def test_count_isomorphisms_h1_also_counted():
    content = "# Cross-Domain Isomorphism 1: X\n## Cross-Domain Isomorphism 2: Y\n"
    assert _count_isomorphism_sections(content) == 2


def test_count_isomorphisms_case_insensitive():
    content = "## CROSS-DOMAIN ISOMORPHISM 1: A\n## cross-domain isomorphism 2: b\n"
    assert _count_isomorphism_sections(content) == 2


def test_unresolved_present():
    assert _has_unresolved_section("## Unresolved Tensions\nstuff\n")
    assert _has_unresolved_section("# Unresolved Tensions\nstuff\n")
    assert not _has_unresolved_section("## Open Questions\nstuff\n")


def test_isomorphism_titles_extraction():
    content = "## Cross-Domain Isomorphism 1: Foo\n## Cross-Domain Isomorphism 2: Bar baz\n"
    titles = _isomorphism_titles(content)
    assert titles == ["Foo", "Bar baz"]


def test_structural_score_complete():
    content = """## Cross-Domain Isomorphism 1: A
## Cross-Domain Isomorphism 2: B
## Cross-Domain Isomorphism 3: C
## Unresolved Tensions
notes
"""
    s = _structural_score(content)
    assert s["isomorphism_section_count"] == 3
    assert s["has_unresolved_tensions"]
    assert s["isomorphism_titles"] == ["A", "B", "C"]


def test_normalize_verdict_run1_a_wins_is_subagent():
    label_map = {"A": "subagent", "B": "teams"}
    assert _normalize_verdict("A-wins", label_map) == "subagent-wins"
    assert _normalize_verdict("B-wins", label_map) == "teams-wins"
    assert _normalize_verdict("tie", label_map) == "tie"


def test_normalize_verdict_run2_swapped_a_wins_is_teams():
    label_map = {"A": "teams", "B": "subagent"}
    assert _normalize_verdict("A-wins", label_map) == "teams-wins"
    assert _normalize_verdict("B-wins", label_map) == "subagent-wins"


def test_normalize_verdict_unknown_returns_inconclusive():
    assert _normalize_verdict("garbage", {"A": "x", "B": "y"}) == "inconclusive"


def test_anti_position_bias_disagreement_yields_inconclusive(tmp_path):
    """If run1 says B-wins and run2 also says B-wins, that's actually disagreement after
    normalization (B was teams in run1, B was subagent in run2). Should yield inconclusive."""
    run1 = {
        "a": {"distinct_isomorphisms": 1},
        "b": {"distinct_isomorphisms": 3},
        "verdict": "B-wins",
    }
    run2 = {
        "a": {"distinct_isomorphisms": 3},
        "b": {"distinct_isomorphisms": 1},
        "verdict": "B-wins",  # In run2 B=subagent — so this means subagent-wins
    }
    r1 = tmp_path / "run1.json"
    r1.write_text(json.dumps(run1))
    r2 = tmp_path / "run2.json"
    r2.write_text(json.dumps(run2))
    out = tmp_path / "report.md"
    cmd = [
        sys.executable,
        str(BENCH),
        "write-report",
        "--review-run-1",
        str(r1),
        "--review-run-2",
        str(r2),
        "--slug",
        "x",
        "--output",
        str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert res.returncode == 0, res.stderr
    envelope = json.loads(res.stdout)
    # Run 1 → teams-wins; Run 2 → subagent-wins → DISAGREE → inconclusive
    assert envelope["run1_verdict"] == "teams-wins"
    assert envelope["run2_verdict"] == "subagent-wins"
    assert envelope["verdict"] == "inconclusive"


def test_anti_position_bias_agreement_yields_consistent_verdict(tmp_path):
    run1 = {
        "a": {"distinct_isomorphisms": 1},
        "b": {"distinct_isomorphisms": 3},
        "verdict": "B-wins",
    }
    run2 = {
        "a": {"distinct_isomorphisms": 3},
        "b": {"distinct_isomorphisms": 1},
        "verdict": "A-wins",  # In run2 A=teams → teams-wins
    }
    r1 = tmp_path / "run1.json"
    r1.write_text(json.dumps(run1))
    r2 = tmp_path / "run2.json"
    r2.write_text(json.dumps(run2))
    out = tmp_path / "report.md"
    cmd = [
        sys.executable,
        str(BENCH),
        "write-report",
        "--review-run-1",
        str(r1),
        "--review-run-2",
        str(r2),
        "--slug",
        "x",
        "--output",
        str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert res.returncode == 0
    envelope = json.loads(res.stdout)
    assert envelope["verdict"] == "teams-wins"


def test_emit_review_prompts_swaps_labels(tmp_path):
    sub = tmp_path / "sub.md"
    sub.write_text("## Cross-Domain Isomorphism 1: SUB-PATTERN\n")
    teams = tmp_path / "teams.md"
    teams.write_text("## Cross-Domain Isomorphism 1: TEAMS-PATTERN\n")
    out_dir = tmp_path / "prompts"
    cmd = [
        sys.executable,
        str(BENCH),
        "emit-review-prompts",
        "--subagent-synthesis",
        str(sub),
        "--teams-synthesis",
        str(teams),
        "--prompt-dir",
        str(out_dir),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert res.returncode == 0
    envelope = json.loads(res.stdout)
    assert envelope["status"] == "prompts_ready"

    run1 = (out_dir / "review-run1-prompt.md").read_text()
    run2 = (out_dir / "review-run2-prompt.md").read_text()
    # Run 1: A=subagent → SUB-PATTERN appears under "## Document A:"
    assert "A=subagent" in run1
    sub_idx = run1.index("## Document A:")
    assert "SUB-PATTERN" in run1[sub_idx : sub_idx + 200]
    # Run 2: A=teams → TEAMS-PATTERN appears under "## Document A:"
    assert "A=teams" in run2
    teams_idx = run2.index("## Document A:")
    assert "TEAMS-PATTERN" in run2[teams_idx : teams_idx + 200]
