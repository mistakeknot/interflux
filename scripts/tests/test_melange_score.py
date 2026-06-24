"""Unit tests for scripts/_melange_score.py — the flux-melange measurement scorer.

Run from the interflux plugin root:
    python3 -m pytest scripts/tests/test_melange_score.py -v

These lock in behaviors verified by hand during the flux-melange evaluation
(experiments E0/E1/E3). The scorer had two real bugs before testing (a
claim-vs-description field mismatch and a jsonl-parse-order bug), and the
matcher had two more (range location, paraphrase under-matching) — these tests
guard all four fixes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import _melange_score as ms  # noqa: E402

GOLD_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "melange"
    / "fixture-token-cache"
    / "ground-truth.json"
)


@pytest.fixture
def gold() -> dict:
    return json.loads(GOLD_PATH.read_text())


# --- helpers to build run findings -----------------------------------------


def claim(text: str, loc: str, **kw) -> dict:
    """A melange-ledger-shaped finding (uses `claim`, not `description`)."""
    f = {"claim": text, "location": loc}
    f.update(kw)
    return f


# --- field-normalization: claim -> description (the first bug found) --------


def test_claim_is_normalized_to_description() -> None:
    f = ms._normalize_finding({"claim": "x", "location": "a.py:1"})
    assert f["description"] == "x"


def test_normalize_does_not_clobber_existing_description() -> None:
    f = ms._normalize_finding(
        {"description": "keep", "claim": "other", "location": "a.py:1"}
    )
    assert f["description"] == "keep"


# --- range-aware location matching (E3 fix) --------------------------------


def test_location_range_containment() -> None:
    # line 44 is INSIDE range 34-45 — FluxBench's start-only parse scored this 0.
    assert ms._range_location_score("token_cache.py:44", "token_cache.py:34-45") == 1.0


def test_location_range_overlap() -> None:
    assert ms._range_location_score("a.py:10-20", "a.py:18-30") == 1.0


def test_location_different_file_is_zero() -> None:
    assert ms._range_location_score("a.py:10", "b.py:10") == 0.0


def test_location_far_apart_is_zero() -> None:
    assert ms._range_location_score("a.py:10", "a.py:100") == 0.0


def test_location_near_miss_proximity() -> None:
    s = ms._range_location_score("a.py:10", "a.py:13")  # gap 3, within +/-5
    assert 0.5 <= s < 1.0


# --- exact-location escape hatch (E3 fix): paraphrases of the same bug ------


def test_exact_location_floors_paraphrase() -> None:
    # Two wordings of the same finding at the same line — SequenceMatcher alone
    # scores this ~0.14 (below threshold); the exact-location escape hatch rescues it.
    m = {
        "description": "lookup trusts the index and never reads the file so purge does not propagate",
        "location": "tc.py:44",
    }
    b = {
        "description": "because the fast path returns the cached secret, a purged credential survives in other processes",
        "location": "tc.py:34-45",
    }
    assert ms.match_score(m, b) >= 0.5


def test_non_matching_location_not_rescued() -> None:
    # Different locations + low desc similarity must NOT match (no false positives).
    m = {"description": "totally unrelated thing about parsing", "location": "tc.py:5"}
    b = {
        "description": "lookup trusts the index and never reads the file",
        "location": "tc.py:90",
    }
    assert ms.match_score(m, b) < ms_threshold()


def ms_threshold() -> float:
    from _fluxbench_score import MATCH_THRESHOLD

    return MATCH_THRESHOLD


# --- the three capability metrics (E1/E3 discrimination) --------------------


def test_good_melange_run_scores_high(gold) -> None:
    """A run surfacing the planted heat findings (g1 fusion, g3 buried, g5 taste)
    scores 1.0 on the melange-specific axes — the construct-validity claim."""
    run = [
        claim(
            "lookup returns the index-cached secret and never touches the file; purge clears only the local index so other processes keep serving the revoked secret",
            "token_cache.py:34-45",
            novelty=3,
            risk={"product": 6},
            source={
                "kind": "fusion",
                "parent_lenses": ["fd-security", "fd-performance"],
            },
            status="upheld",
        ),
        claim(
            "path traversal: token_id concatenated into path escapes CACHE_DIR",
            "token_cache.py:21-23",
            novelty=1,
            risk={"product": 9},
            source={"kind": "lens"},
            status="upheld",
        ),
        claim(
            "purge_all is not atomic or multi-process safe; races with store during rotation leaving revoked secrets on disk",
            "token_cache.py:48-51",
            novelty=2,
            risk={"product": 3},
            source={"kind": "lens"},
            status="upheld",
        ),
        claim(
            "_index dual-store asymmetry: secret written to file and index with no single source of truth; a write-through type prevents the g1 class",
            "token_cache.py:18",
            novelty=2,
            risk={"product": 1},
            taste=2,
            taste_kind="asymmetry",
            source={"kind": "lens"},
            status="upheld",
        ),
    ]
    r = ms.score(run, gold)
    assert r["frontier_recall"] == 1.0
    assert r["buried_recall"] == 1.0
    assert r["fusion_emergent_recall"] == 1.0
    assert r["taste_recall"] == 1.0
    assert r["false_positive_rate"] == 0.0


def test_severity_only_baseline_misses_melange_axes(gold) -> None:
    """A severity-ranked baseline that only reports the obvious high-severity
    findings scores 0 on buried/fusion — the axes severity ranking buries."""
    run = [
        {
            "description": "path traversal: token_id concatenated into filesystem path escapes CACHE_DIR",
            "location": "token_cache.py:21-23",
            "severity": "P0",
        },
        {
            "description": "store has no exception handling and does not create CACHE_DIR",
            "location": "token_cache.py:26-31",
            "severity": "P1",
        },
    ]
    r = ms.score(run, gold)
    assert r["buried_recall"] == 0.0
    assert r["fusion_emergent_recall"] == 0.0


def test_fusion_match_requires_fusion_source(gold) -> None:
    """A finding matching the requires_fusion gold (g1) only counts as
    fusion-emergent if its OWN source.kind is fusion — a single lens finding the
    same location does NOT earn the emergent credit."""
    single = [
        claim(
            "lookup returns the index-cached secret and never touches the file; purge does not propagate to other processes",
            "token_cache.py:34-45",
            novelty=2,
            risk={"product": 6},
            source={"kind": "lens"},
            status="upheld",
        )
    ]
    r = ms.score(single, gold)
    # matches g1's location/desc but is not a fusion source -> no emergent credit
    assert r["fusion_emergent_recall"] == 0.0


# --- robustness (E0: a real ledger may be empty, partial, or crash mid-run) -


def test_empty_run_is_clean_zeros(gold) -> None:
    r = ms.score([], gold)
    assert r["n_run_findings"] == 0
    assert r["frontier_recall"] == 0.0
    assert r["false_positive_rate"] == 0.0


def test_load_run_skips_malformed_jsonl(tmp_path) -> None:
    p = tmp_path / "ledger.jsonl"
    p.write_text(
        "\n".join(
            [
                json.dumps({"id": "f1", "claim": "ok", "location": "a.py:1"}),
                "THIS IS NOT JSON",
                json.dumps({"id": "f2", "claim": "ok2", "location": "a.py:2"}),
            ]
        )
    )
    run = ms._load_run(str(p))
    assert len(run) == 2  # malformed line skipped, valid lines kept
    assert all("description" in f for f in run)  # claim normalized


def test_load_run_jsonl_not_truncated_to_first_line(tmp_path) -> None:
    """Regression: the original loader tried flat-json first; a jsonl file's first
    line parses as valid JSON, so it returned only that line. Must read ALL lines."""
    p = tmp_path / "ledger.jsonl"
    p.write_text(
        "\n".join(
            json.dumps({"id": f"f{i}", "claim": "c", "location": f"a.py:{i}"})
            for i in range(5)
        )
    )
    assert len(ms._load_run(str(p))) == 5


def test_load_run_accepts_flat_findings_json(tmp_path) -> None:
    p = tmp_path / "flat.json"
    p.write_text(json.dumps({"findings": [{"description": "x", "location": "a.py:1"}]}))
    assert len(ms._load_run(str(p))) == 1


# --- surfaced view (E1 fix): score the report, not the raw ledger -----------


def test_surfaced_view_drops_refuted() -> None:
    run = [
        {
            "claim": "real",
            "location": "a.py:1",
            "novelty": 3,
            "risk": {"product": 6},
            "status": "upheld",
        },
        {
            "claim": "hallucinated",
            "location": "a.py:2",
            "novelty": 3,
            "risk": {"product": 6},
            "status": "refuted",
        },
    ]
    view = ms._surfaced_view("/nonexistent/ledger.jsonl", run)
    claims = {f["claim"] for f in view}
    assert "real" in claims
    assert "hallucinated" not in claims  # refuted never surfaces


def test_surfaced_view_flat_baseline_is_noop() -> None:
    """A flat baseline (no status/heat) is returned unchanged — nothing to filter."""
    run = [{"description": "x", "location": "a.py:1", "severity": "P0"}]
    assert ms._surfaced_view("/nonexistent/ledger.jsonl", run) == run
