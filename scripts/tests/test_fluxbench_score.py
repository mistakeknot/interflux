"""Unit tests for scripts/_fluxbench_score.py.

Run from the interflux plugin root:
    python3 -m pytest scripts/tests/test_fluxbench_score.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import _fluxbench_score as fbs  # noqa: E402

SCRIPT = str(ROOT / "scripts" / "_fluxbench_score.py")


# Helpers


def F(severity: str, location: str = "x.py:10", description: str = "issue") -> dict:
    """Build a finding dict succinctly."""
    return {"severity": severity, "location": location, "description": description}


# --- _sev (severity normalization) -----------------------------------------


def test_sev_strips_whitespace() -> None:
    assert fbs._sev({"severity": "P0 "}) == "P0"
    assert fbs._sev({"severity": "  P1  "}) == "P1"


def test_sev_uppercases() -> None:
    assert fbs._sev({"severity": "p0"}) == "P0"
    assert fbs._sev({"severity": "p2"}) == "P2"


def test_sev_handles_missing() -> None:
    assert fbs._sev({}) == ""
    assert fbs._sev({"severity": None}) == ""


# --- location_score --------------------------------------------------------


def test_location_score_exact() -> None:
    assert fbs.location_score("foo.py:10", "foo.py:10") == 1.0
    assert fbs.location_score("./foo.py:10", "foo.py:10") == 1.0  # leading ./ stripped
    assert fbs.location_score("FOO.py:10", "foo.py:10") == 1.0  # case-insensitive


def test_location_score_same_file_close_lines() -> None:
    # delta=2 → 1.0 - 2*0.1 = 0.8
    assert fbs.location_score("foo.py:10", "foo.py:12") == pytest.approx(0.8)
    # delta=5 → max(0.5, 1.0 - 5*0.1) = 0.5
    assert fbs.location_score("foo.py:10", "foo.py:15") == 0.5


def test_location_score_same_file_far_lines() -> None:
    # delta=6 → 0 (no credit beyond ±5)
    assert fbs.location_score("foo.py:10", "foo.py:16") == 0.0


def test_location_score_different_file() -> None:
    assert fbs.location_score("foo.py:10", "bar.py:10") == 0.0


def test_location_score_no_lines() -> None:
    assert fbs.location_score("foo.py", "foo.py") == 1.0
    assert fbs.location_score("foo.py", "bar.py") == 0.0


# --- match_score ----------------------------------------------------------


def test_match_score_exact_location_and_description() -> None:
    a = {"location": "foo.py:10", "description": "null check missing"}
    b = {"location": "foo.py:10", "description": "null check missing"}
    assert fbs.match_score(a, b) == pytest.approx(1.0)


def test_match_score_location_match_partial_description() -> None:
    a = {"location": "foo.py:10", "description": "null check missing"}
    b = {"location": "foo.py:10", "description": "missing null check"}
    s = fbs.match_score(a, b)
    assert 0.5 < s < 1.0  # location 1.0 × desc ratio (~0.7+)


def test_match_score_location_mismatch_high_description() -> None:
    """Description ≥0.60 with location mismatch gets 0.4 × desc_ratio."""
    a = {"location": "foo.py:10", "description": "null pointer exception"}
    b = {"location": "bar.py:10", "description": "null pointer exception"}
    s = fbs.match_score(a, b)
    # desc_ratio = 1.0, location mismatch → 0.4 * 1.0 = 0.4
    assert s == pytest.approx(0.4)


def test_match_score_low_similarity_returns_zero() -> None:
    a = {"location": "foo.py:10", "description": "totally different thing"}
    b = {"location": "bar.py:10", "description": "race condition in lock"}
    assert fbs.match_score(a, b) == 0.0


# --- hungarian_maximize ---------------------------------------------------


def test_hungarian_empty() -> None:
    assert fbs.hungarian_maximize([]) == []
    assert fbs.hungarian_maximize([[]]) == []


def test_hungarian_one_to_one() -> None:
    result = fbs.hungarian_maximize([[1.0]])
    assert result == [(0, 0)]


def test_hungarian_optimal_not_greedy() -> None:
    """Verify Hungarian picks the global optimum, not the greedy local choice.

    Greedy on row 0 would pick col 1 (0.9 > 0.8), forcing row 1 → col 0 (0.5).
    Total greedy: 0.9 + 0.5 = 1.4.
    Optimal: row 0 → col 0 (0.8), row 1 → col 1 (1.0). Total: 1.8.
    """
    matrix = [
        [0.8, 0.9],
        [0.5, 1.0],
    ]
    result = fbs.hungarian_maximize(matrix)
    matched = dict(result)
    # Optimal assignment is (0, 0) and (1, 1)
    assert matched == {0: 0, 1: 1}


def test_hungarian_drops_below_threshold() -> None:
    """Pairs scoring < 0.20 are dropped (algorithm fills the bijection but they don't count)."""
    matrix = [
        [0.05, 0.10],
        [0.90, 0.50],
    ]
    result = fbs.hungarian_maximize(matrix)
    matched = dict(result)
    # Row 1 must match col 0 (its only score ≥ 0.20). Row 0 has no match ≥ 0.20.
    assert 1 in matched
    assert matched[1] == 0
    assert 0 not in matched


def test_hungarian_unequal_dimensions() -> None:
    """Non-square matrix: more rows than cols (excess rows unmatched)."""
    matrix = [
        [0.9, 0.1],
        [0.2, 0.8],
        [0.5, 0.4],
    ]
    result = fbs.hungarian_maximize(matrix)
    # Optimal: 0→0, 1→1. Row 2 unmatched.
    matched = dict(result)
    assert matched.get(0) == 0
    assert matched.get(1) == 1


# --- score_findings: empty cases ------------------------------------------


def test_score_both_empty() -> None:
    r = fbs.score_findings([], [], 1.0)
    assert r["recall"] == 1
    assert r["fp_rate"] == 0
    assert r["severity_accuracy"] == 1
    assert r["p0_auto_fail"] is False
    assert r["matched"] == 0


def test_score_empty_baseline_with_model_findings() -> None:
    """Model reports findings but baseline is empty → all FPs, recall=1.0 (vacuous)."""
    r = fbs.score_findings([F("P1")], [], 1.0)
    assert r["recall"] == 1  # vacuous recall when baseline empty
    assert r["fp_rate"] == 1  # 1 of 1 model findings unmatched
    assert r["matched"] == 0


def test_score_empty_model_with_baseline() -> None:
    """Baseline has findings but model reports none → recall=0, fp=0."""
    r = fbs.score_findings([], [F("P1")], 1.0)
    assert r["recall"] == 0
    assert r["fp_rate"] == 0
    assert r["matched"] == 0
    assert r["baseline_only"] == 1


# --- P0 auto-fail ---------------------------------------------------------


def test_p0_auto_fail_unmatched_p0() -> None:
    model = [F("P1", "foo.py:10", "small bug")]
    baseline = [F("P0", "critical.py:5", "data loss bug")]
    r = fbs.score_findings(model, baseline, 1.0)
    assert r["p0_auto_fail"] is True
    assert r["gate_recall"] is False  # auto-fail forces gate fail


def test_p0_auto_fail_severity_downgrade() -> None:
    """Matched P0 in baseline reported as P1 in model → auto-fail."""
    model = [F("P1", "foo.py:10", "null check missing")]
    baseline = [F("P0", "foo.py:10", "null check missing")]
    r = fbs.score_findings(model, baseline, 1.0)
    assert r["p0_auto_fail"] is True


def test_p0_no_auto_fail_when_matched_correctly() -> None:
    model = [F("P0", "foo.py:10", "null check missing")]
    baseline = [F("P0", "foo.py:10", "null check missing")]
    r = fbs.score_findings(model, baseline, 1.0)
    assert r["p0_auto_fail"] is False


def test_p0_auto_fail_tolerates_severity_whitespace() -> None:
    """LLM output 'P0 ' (trailing space) should still match P0."""
    model = [{"severity": "P0 ", "location": "foo.py:10", "description": "x"}]
    baseline = [{"severity": "P0", "location": "foo.py:10", "description": "x"}]
    r = fbs.score_findings(model, baseline, 1.0)
    assert r["p0_auto_fail"] is False


def test_p0_auto_fail_tolerates_lowercase() -> None:
    model = [{"severity": "p0", "location": "foo.py:10", "description": "x"}]
    baseline = [{"severity": "P0", "location": "foo.py:10", "description": "x"}]
    r = fbs.score_findings(model, baseline, 1.0)
    assert r["p0_auto_fail"] is False


# --- severity_accuracy (±1 tolerance) -------------------------------------


def test_severity_accuracy_exact() -> None:
    model = [F("P1", "foo.py:10", "x"), F("P2", "bar.py:10", "y")]
    baseline = [F("P1", "foo.py:10", "x"), F("P2", "bar.py:10", "y")]
    r = fbs.score_findings(model, baseline, 1.0)
    assert r["severity_accuracy"] == 1


def test_severity_accuracy_within_one_level() -> None:
    """P1 vs P2 = ±1 = OK."""
    model = [F("P1", "foo.py:10", "x")]
    baseline = [F("P2", "foo.py:10", "x")]
    r = fbs.score_findings(model, baseline, 1.0)
    assert r["severity_accuracy"] == 1  # |1-2|=1, within tolerance


def test_severity_accuracy_two_levels_apart() -> None:
    """P1 vs P3 = ±2 = FAIL the accuracy check."""
    model = [F("P1", "foo.py:10", "x")]
    baseline = [F("P3", "foo.py:10", "x")]
    r = fbs.score_findings(model, baseline, 1.0)
    # P1=1, P3=3, |1-3|=2 → not within tolerance
    assert r["severity_accuracy"] == 0


# --- recall (severity-weighted) -------------------------------------------


def test_recall_full_match() -> None:
    model = [F("P1", "foo.py:10", "x")]
    baseline = [F("P1", "foo.py:10", "x")]
    r = fbs.score_findings(model, baseline, 1.0)
    assert r["recall"] == 1


def test_recall_partial_match_p0_dominates() -> None:
    """P0 weight=4, P1 weight=2. Catching P0 alone gives 4/(4+2) ≈ 0.67."""
    # Make sure model also reports its own P0 (so no auto-fail)
    model = [F("P0", "a.py:10", "p0 bug")]
    baseline = [F("P0", "a.py:10", "p0 bug"), F("P1", "b.py:20", "p1 bug")]
    r = fbs.score_findings(model, baseline, 1.0)
    assert r["recall"] == pytest.approx(4 / 6, abs=1e-3)


# --- gate verdicts --------------------------------------------------------


def test_gate_format_compliance() -> None:
    r = fbs.score_findings([], [], format_compliance=0.94, t_format=0.95)
    assert r["gate_format"] is False
    r = fbs.score_findings([], [], format_compliance=0.95, t_format=0.95)
    assert r["gate_format"] is True


def test_gate_fp_rate() -> None:
    """Many false positives fail the FP gate."""
    model = [F("P1", "a.py", "x"), F("P1", "b.py", "y"), F("P1", "c.py", "z")]
    baseline = [F("P1", "a.py", "x")]
    r = fbs.score_findings(model, baseline, 1.0, t_fp=0.20)
    # 2 of 3 model findings are unmatched → fp_rate=0.6667 > 0.20
    assert r["gate_fp"] is False


def test_gate_recall_blocked_by_p0_auto_fail() -> None:
    """Even with high recall, P0 auto-fail forces gate_recall=False."""
    # Match a P0 but downgrade it
    model = [F("P1", "foo.py:10", "p0 bug")]
    baseline = [F("P0", "foo.py:10", "p0 bug")]
    r = fbs.score_findings(model, baseline, 1.0, t_recall=0.0)
    assert r["p0_auto_fail"] is True
    assert r["gate_recall"] is False


# --- CLI ------------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_perfect_match(tmp_path: Path) -> None:
    model = tmp_path / "m.json"
    base = tmp_path / "b.json"
    findings = [F("P1", "foo.py:10", "null check")]
    model.write_text(json.dumps(findings))
    base.write_text(json.dumps(findings))
    result = _run_cli(str(model), str(base), "1.0")
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["recall"] == 1
    assert output["matched"] == 1
    assert output["p0_auto_fail"] is False


def test_cli_p0_auto_fail(tmp_path: Path) -> None:
    model = tmp_path / "m.json"
    base = tmp_path / "b.json"
    model.write_text(json.dumps([F("P1", "foo.py:10", "small")]))
    base.write_text(json.dumps([F("P0", "critical.py:5", "data loss")]))
    result = _run_cli(str(model), str(base), "1.0")
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["p0_auto_fail"] is True
    assert output["gate_recall"] is False


def test_cli_threshold_overrides(tmp_path: Path) -> None:
    """--t-format=0.99 makes a 0.95 compliance fail the gate."""
    model = tmp_path / "m.json"
    base = tmp_path / "b.json"
    model.write_text("[]")
    base.write_text("[]")
    result = _run_cli(str(model), str(base), "0.95", "--t-format", "0.99")
    assert result.returncode == 0
    assert json.loads(result.stdout)["gate_format"] is False


def test_cli_missing_file(tmp_path: Path) -> None:
    base = tmp_path / "b.json"
    base.write_text("[]")
    result = _run_cli(str(tmp_path / "nonexistent.json"), str(base), "1.0")
    assert result.returncode == 2


def test_cli_corrupt_json(tmp_path: Path) -> None:
    model = tmp_path / "m.json"
    base = tmp_path / "b.json"
    model.write_text("{not json")
    base.write_text("[]")
    result = _run_cli(str(model), str(base), "1.0")
    assert result.returncode == 2


def test_cli_non_array_input(tmp_path: Path) -> None:
    model = tmp_path / "m.json"
    base = tmp_path / "b.json"
    model.write_text('{"not": "an array"}')
    base.write_text("[]")
    result = _run_cli(str(model), str(base), "1.0")
    assert result.returncode == 2
    assert "expected a JSON array" in result.stderr
