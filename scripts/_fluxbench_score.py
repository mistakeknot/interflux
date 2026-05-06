"""FluxBench scoring algorithm — extracted from fluxbench-score.sh heredoc.

Computes finding-recall, false-positive-rate, severity-accuracy, and gate
verdicts for a model's findings against a baseline. Uses the Hungarian
algorithm for optimal bipartite matching of findings.

Public function:
    score_findings(model_findings, baseline_findings, format_compliance,
                   t_format=0.95, t_recall=0.60, t_fp=0.20, t_severity=0.70)
        -> dict (full score report including gate verdicts)

CLI:
    python3 _fluxbench_score.py <model.json> <baseline.json> <format-compliance>
        [--t-format X] [--t-recall X] [--t-fp X] [--t-severity X]

Each *.json file is a JSON array of finding objects. format-compliance is a
float in [0.0, 1.0]. Outputs the score report as JSON to stdout. Exit 0 on
success, 2 on input-parse error.
"""
from __future__ import annotations

import argparse
import json
import sys
from difflib import SequenceMatcher
from typing import Any

# Severity weights for recall computation (P0 dominates).
WEIGHTS = {"P0": 4, "P1": 2, "P2": 1, "P3": 0.5}
# Severity levels for ±1 accuracy check.
SEV_LEVELS = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
# Minimum score for a Hungarian match to count as a real match.
MATCH_THRESHOLD = 0.20


def _sev(finding: dict[str, Any]) -> str:
    """Normalize severity: trim whitespace, uppercase. LLM output often has 'P0 ' or 'p0'."""
    return (finding.get("severity") or "").strip().upper()


def _normalize_location(loc: str) -> str:
    return loc.lstrip("./").lower()


def _parse_loc_parts(loc: str) -> tuple[str, int | None]:
    """Split 'file.py:10-12' → ('file.py', 10) or ('file.py', None) if no line."""
    parts = loc.split(":")
    if len(parts) < 2:
        return (loc, None)
    try:
        line = int(parts[1].split("-")[0])
        return (parts[0], line)
    except ValueError:
        return (parts[0], None)


def location_score(m_loc: str, b_loc: str) -> float:
    """Fuzzy location matching: exact=1.0, same file ±5 lines=0.5–0.9, else 0."""
    m_norm = _normalize_location(m_loc)
    b_norm = _normalize_location(b_loc)
    if m_norm == b_norm:
        return 1.0
    m_file, m_line = _parse_loc_parts(m_norm)
    b_file, b_line = _parse_loc_parts(b_norm)
    if m_file != b_file:
        return 0.0
    if m_line is not None and b_line is not None:
        delta = abs(m_line - b_line)
        if delta <= 5:
            return max(0.5, 1.0 - delta * 0.1)
    return 0.0


def match_score(m: dict[str, Any], b: dict[str, Any]) -> float:
    """Combine description-similarity (SequenceMatcher) and location_score."""
    desc_ratio = SequenceMatcher(
        None,
        m.get("description", "").lower(),
        b.get("description", "").lower(),
    ).ratio()
    loc_s = location_score(m.get("location", ""), b.get("location", ""))
    if loc_s > 0:
        return loc_s * desc_ratio
    # Location mismatch but high description similarity → credit with penalty
    if desc_ratio >= 0.60:
        return 0.4 * desc_ratio
    return 0.0


def hungarian_maximize(score_matrix: list[list[float]]) -> list[tuple[int, int]]:
    """Optimal assignment for small matrices. Returns list of (row, col) pairs.

    Pairs scoring below MATCH_THRESHOLD (0.20) are dropped — those are
    spurious matches the algorithm assigns to fill the bijection.
    """
    n = len(score_matrix)
    if n == 0:
        return []
    m = len(score_matrix[0]) if n > 0 else 0
    if m == 0:
        return []

    size = max(n, m)
    max_val = max(max(row) for row in score_matrix) if score_matrix else 0
    cost = [[0.0] * size for _ in range(size)]
    # Convert max-assignment to min-assignment (negate scores).
    for i in range(n):
        for j in range(m):
            cost[i][j] = max_val - score_matrix[i][j]

    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)

    for i in range(1, size + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (size + 1)
        used = [False] * (size + 1)

        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = -1
            for j in range(1, size + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(size + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break

        while j0:
            p[j0] = p[way[j0]]
            j0 = way[j0]

    result: list[tuple[int, int]] = []
    for j in range(1, size + 1):
        if p[j] != 0 and p[j] <= n and j <= m:
            if score_matrix[p[j] - 1][j - 1] >= MATCH_THRESHOLD:
                result.append((p[j] - 1, j - 1))
    return result


def _clean_num(v: float) -> float | int:
    """Convert whole-number floats to int for clean JSON (1.0 -> 1)."""
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


def score_findings(
    model_findings: list[dict[str, Any]],
    baseline_findings: list[dict[str, Any]],
    format_compliance: float,
    t_format: float = 0.95,
    t_recall: float = 0.60,
    t_fp: float = 0.20,
    t_severity: float = 0.70,
) -> dict[str, Any]:
    """Run the full scoring pipeline and return metrics + gate verdicts."""
    # Build score matrix and run Hungarian.
    n_model = len(model_findings)
    n_baseline = len(baseline_findings)
    if n_model > 0 and n_baseline > 0:
        score_matrix = [
            [match_score(model_findings[mi], baseline_findings[bi]) for bi in range(n_baseline)]
            for mi in range(n_model)
        ]
        matched_pairs = hungarian_maximize(score_matrix)
    else:
        matched_pairs = []

    used_model = {mi for mi, _ in matched_pairs}
    used_baseline = {bi for _, bi in matched_pairs}
    model_only_idxs = [i for i in range(n_model) if i not in used_model]
    baseline_only_idxs = [i for i in range(n_baseline) if i not in used_baseline]

    # Severity-weighted recall.
    total_weight = sum(WEIGHTS.get(bf.get("severity", "P2"), 1) for bf in baseline_findings)
    found_weight = sum(
        WEIGHTS.get(baseline_findings[bi].get("severity", "P2"), 1) for _, bi in matched_pairs
    )

    if total_weight == 0:
        # Empty baseline → vacuous recall. Note: any model findings in this case
        # all become FPs (fp_rate computed below).
        recall = 1.0
    elif found_weight == 0:
        recall = 0.0
    else:
        recall = round(found_weight / total_weight, 4)

    # P0 auto-fail: any unmatched P0 in baseline.
    matched_baseline_idxs = {bi for _, bi in matched_pairs}
    p0_auto_fail = False
    for bi in range(n_baseline):
        if _sev(baseline_findings[bi]) == "P0" and bi not in matched_baseline_idxs:
            p0_auto_fail = True
            break

    # P0 severity downgrade check: matched P0 must be reported as P0.
    if not p0_auto_fail:
        for mi, bi in matched_pairs:
            if _sev(baseline_findings[bi]) == "P0" and _sev(model_findings[mi]) != "P0":
                p0_auto_fail = True
                break

    # False positive rate.
    if n_model == 0:
        fp_rate = 0.0
    else:
        fp_rate = round(len(model_only_idxs) / n_model, 4)

    # Severity accuracy: % of matched where severity is ±1 level.
    sev_accurate = 0
    for mi, bi in matched_pairs:
        m_sev = SEV_LEVELS.get(model_findings[mi].get("severity", "P2"), 2)
        b_sev = SEV_LEVELS.get(baseline_findings[bi].get("severity", "P2"), 2)
        if abs(m_sev - b_sev) <= 1:
            sev_accurate += 1
    if len(matched_pairs) == 0:
        severity_accuracy = 1.0 if n_baseline == 0 else 0.0
    else:
        severity_accuracy = round(sev_accurate / len(matched_pairs), 4)

    # Disagreement rate (currently identical to FP rate).
    if n_model == 0:
        disagreement_rate = 0.0
    else:
        disagreement_rate = round(len(model_only_idxs) / n_model, 4)

    # Gate evaluation.
    gate_format = format_compliance >= t_format
    gate_recall = recall >= t_recall and not p0_auto_fail
    gate_fp = fp_rate <= t_fp
    gate_severity = severity_accuracy >= t_severity

    return {
        "recall": _clean_num(recall),
        "fp_rate": _clean_num(fp_rate),
        "severity_accuracy": _clean_num(severity_accuracy),
        "p0_auto_fail": p0_auto_fail,
        "disagreement_rate": _clean_num(disagreement_rate),
        "matched": len(matched_pairs),
        "model_only": len(model_only_idxs),
        "baseline_only": len(baseline_only_idxs),
        "gate_format": gate_format,
        "gate_recall": gate_recall,
        "gate_fp": gate_fp,
        "gate_severity": gate_severity,
    }


def _load_findings(path: str) -> list[dict[str, Any]]:
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array of findings, got {type(data).__name__}")
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    p.add_argument("model_findings", help="Path to JSON array of model findings")
    p.add_argument("baseline_findings", help="Path to JSON array of baseline findings")
    p.add_argument("format_compliance", type=float, help="Format compliance rate in [0, 1]")
    p.add_argument("--t-format", type=float, default=0.95)
    p.add_argument("--t-recall", type=float, default=0.60)
    p.add_argument("--t-fp", type=float, default=0.20)
    p.add_argument("--t-severity", type=float, default=0.70)
    args = p.parse_args(argv)

    try:
        model = _load_findings(args.model_findings)
        baseline = _load_findings(args.baseline_findings)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        print(f"_fluxbench_score: {exc}", file=sys.stderr)
        return 2

    result = score_findings(
        model,
        baseline,
        args.format_compliance,
        t_format=args.t_format,
        t_recall=args.t_recall,
        t_fp=args.t_fp,
        t_severity=args.t_severity,
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
