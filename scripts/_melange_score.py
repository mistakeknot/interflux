#!/usr/bin/env python3
"""Melange-aware scoring: measures the three capabilities flux-melange CLAIMS,
not the severity-weighted recall FluxBench measures (which would under-measure
melange by scoring it on the axis it deliberately rejects).

Reuses the FluxBench finding-matcher (fuzzy location x description, Hungarian
assignment) to align a melange run's findings to a heat-labeled gold set, then
computes construct-valid metrics:

  1. frontier_recall      — of gold findings on the novelty x risk frontier,
                            how many did the run surface? (the core claim)
  2. buried_recall        — did the run surface the buried-by-severity finding
                            (low severity, high risk.product)? vs a severity-only
                            baseline that would bury it.
  3. fusion_emergent      — did a fusion finding match the gold finding tagged
                            requires_fusion? (emergence detector worked)
  4. taste_surfaced       — did the run surface the taste-tagged gold finding?
  5. assayer_kappa-lite   — agreement between run novelty/risk scores and gold
                            labels on matched pairs (validates the Assayer).
  6. false_positive_rate  — run findings that match no gold finding.

Usage:
  _melange_score.py <run-ledger.jsonl> <ground-truth.json> [--json]

The run ledger is heat-ledger.jsonl (one finding object per line, melange schema).
Also accepts a flat {"findings":[...]} JSON (for scoring flux-review output against
the same gold set in head-to-head experiments).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Reuse the FluxBench matcher — same dir.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fluxbench_score import match_score, hungarian_maximize, MATCH_THRESHOLD  # noqa: E402


def _risk_product(f: dict[str, Any]) -> int:
    r = f.get("risk") or {}
    if "product" in r:
        return int(r["product"])
    return int(r.get("blast_radius", 0)) * int(r.get("likelihood", 0))


def _heat(f: dict[str, Any]) -> int:
    """Steering/surfacing rank = novelty x risk.product (heat-scoring.md)."""
    return int(f.get("novelty", 0)) * _risk_product(f)


def _normalize_finding(f: dict[str, Any]) -> dict[str, Any]:
    """The melange ledger names the finding text `claim` (ledger-schema.md), but the
    FluxBench matcher keys on `description`. Map it so the fuzzy matcher works across
    both schemas. (This interop gap was found during eval — the matcher silently
    scored every claim-only finding as 0 description-similarity.)"""
    if "description" not in f and "claim" in f:
        f = dict(f)
        f["description"] = f["claim"]
    return f


def _load_run(path: str) -> list[dict[str, Any]]:
    """Load a melange ledger (jsonl) or a flat {findings:[...]} json."""
    text = Path(path).read_text().strip()
    if not text:
        return []
    raw: list[dict[str, Any]] = []
    # Try flat json first.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "findings" in obj:
            raw = obj["findings"]
        elif isinstance(obj, list):
            raw = obj
    except json.JSONDecodeError:
        # jsonl
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return [_normalize_finding(f) for f in raw]


def _pareto_front(findings: list[dict[str, Any]]) -> list[int]:
    """Indices of gold findings on the (novelty, risk.product) Pareto front —
    not dominated on BOTH axes by another finding. This is what melange's
    synthesis view 1 is supposed to surface."""
    front = []
    for i, fi in enumerate(findings):
        ni, ri = int(fi.get("novelty", 0)), _risk_product(fi)
        dominated = False
        for j, fj in enumerate(findings):
            if i == j:
                continue
            nj, rj = int(fj.get("novelty", 0)), _risk_product(fj)
            if (nj >= ni and rj >= ri) and (nj > ni or rj > ri):
                dominated = True
                break
        if not dominated:
            front.append(i)
    return front


def _match(run: list[dict[str, Any]], gold: list[dict[str, Any]]) -> dict[int, int]:
    """gold_index -> run_index for matched pairs (>= MATCH_THRESHOLD)."""
    if not run or not gold:
        return {}
    matrix = [[match_score(g, r) for r in run] for g in gold]
    pairs = hungarian_maximize(matrix)
    out = {}
    for gi, ri in pairs:
        if gi < len(gold) and ri < len(run) and matrix[gi][ri] >= MATCH_THRESHOLD:
            out[gi] = ri
    return out


def score(run: list[dict[str, Any]], gold_doc: dict[str, Any]) -> dict[str, Any]:
    gold = gold_doc["findings"]
    matched = _match(run, gold)  # gold_idx -> run_idx

    front_idxs = set(_pareto_front(gold))
    front_total = len(front_idxs)
    front_found = sum(1 for gi in matched if gi in front_idxs)

    # buried finding (tagged buried_by_severity)
    buried_idxs = [i for i, g in enumerate(gold) if g.get("buried_by_severity")]
    buried_found = sum(1 for gi in matched if gi in buried_idxs)

    # fusion-emergent: gold tagged requires_fusion AND the matching run finding
    # is itself a fusion finding (source.kind == fusion).
    fusion_gold = [i for i, g in enumerate(gold) if g.get("requires_fusion")]
    fusion_emergent_hits = 0
    for gi in fusion_gold:
        if gi in matched:
            rf = run[matched[gi]]
            src = rf.get("source") or {}
            if (
                src.get("kind") == "fusion"
                or rf.get("parent_lenses")
                or src.get("parent_lenses")
            ):
                fusion_emergent_hits += 1

    # taste: gold with |taste| >= 2 that got surfaced
    taste_gold = [i for i, g in enumerate(gold) if abs(int(g.get("taste", 0))) >= 2]
    taste_found = sum(1 for gi in matched if gi in taste_gold)

    # assayer agreement (kappa-lite): fraction of matched pairs whose run novelty
    # is within 1 of gold AND run risk.product within 2 of gold.
    agree = 0
    for gi, ri in matched.items():
        g, r = gold[gi], run[ri]
        nov_ok = abs(int(r.get("novelty", -9)) - int(g.get("novelty", 0))) <= 1
        risk_ok = abs(_risk_product(r) - _risk_product(g)) <= 2
        if nov_ok and risk_ok:
            agree += 1
    assayer_agreement = (agree / len(matched)) if matched else None

    fp = len(run) - len(set(matched.values()))
    fp_rate = (fp / len(run)) if run else 0.0

    return {
        "n_run_findings": len(run),
        "n_gold_findings": len(gold),
        "n_matched": len(matched),
        "frontier_recall": round(front_found / front_total, 3) if front_total else None,
        "frontier_found": front_found,
        "frontier_total": front_total,
        "buried_recall": round(buried_found / len(buried_idxs), 3)
        if buried_idxs
        else None,
        "buried_finding_ids": [gold[i].get("id") for i in buried_idxs],
        "buried_found": buried_found,
        "fusion_emergent_recall": round(fusion_emergent_hits / len(fusion_gold), 3)
        if fusion_gold
        else None,
        "fusion_emergent_hits": fusion_emergent_hits,
        "fusion_gold_ids": [gold[i].get("id") for i in fusion_gold],
        "taste_recall": round(taste_found / len(taste_gold), 3) if taste_gold else None,
        "taste_found": taste_found,
        "assayer_agreement": round(assayer_agreement, 3)
        if assayer_agreement is not None
        else None,
        "false_positive_rate": round(fp_rate, 3),
        "matched_pairs": {gold[gi].get("id", gi): matched[gi] for gi in matched},
    }


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    if len(args) != 2:
        print(__doc__)
        return 2
    run = _load_run(args[0])
    gold_doc = json.loads(Path(args[1]).read_text())
    result = score(run, gold_doc)
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"run findings:        {result['n_run_findings']}")
        print(
            f"gold findings:       {result['n_gold_findings']}  matched: {result['n_matched']}"
        )
        print(
            f"frontier recall:     {result['frontier_recall']}  ({result['frontier_found']}/{result['frontier_total']})"
        )
        print(
            f"buried recall:       {result['buried_recall']}  (the rare-catastrophe class severity buries)"
        )
        print(
            f"fusion emergent:     {result['fusion_emergent_recall']}  ({result['fusion_emergent_hits']}/{len(result['fusion_gold_ids'])})"
        )
        print(f"taste surfaced:      {result['taste_recall']}")
        print(
            f"assayer agreement:   {result['assayer_agreement']}  (novelty±1 & risk±2 vs gold)"
        )
        print(f"false positive rate: {result['false_positive_rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
