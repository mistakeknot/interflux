"""Unit tests for cluster_specs.py.

Run: python3 -m pytest interverse/interflux/tests/test_cluster_specs.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Allow importing the script as a module
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from cluster_specs import (  # noqa: E402
    _distance,
    _spec_text,
    _trigrams,
    cluster_specs,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SPECS_DIR = REPO_ROOT / ".claude" / "flux-gen-specs"


def _make_spec(domain: str, focus: str, expected: str, name: str | None = None) -> dict:
    return {
        "name": name or f"fd-{domain.replace(' ', '-')}",
        "source_domain": domain,
        "focus": focus,
        "expected_isomorphisms": expected,
    }


def test_trigram_distance_self_zero():
    v = _trigrams("hello world")
    assert _distance(v, v) == pytest.approx(0.0, abs=1e-6)


def test_trigram_distance_disjoint_high():
    a = _trigrams("biology immune cells")
    b = _trigrams("xenophilic quartzite mineralogy")
    # Should be near 1.0 — almost no shared trigrams
    assert _distance(a, b) > 0.9


def test_spec_text_concatenation():
    spec = _make_spec("Biology", "Immune Tolerance", "T-cell P maps to circuit Q")
    text = _spec_text(spec)
    assert "biology" in text
    assert "immune tolerance" in text
    assert "t-cell" in text


def test_three_widely_separated_domains_yields_three_balanced_clusters():
    """9 specs from 3 widely-separated domains → 3 balanced clusters above threshold."""
    specs = (
        # Biology
        [
            _make_spec(
                "evolutionary biology",
                f"natural selection mechanism {i}",
                "fitness landscape maps to optimization surface via gradient descent",
                f"fd-bio-{i}",
            )
            for i in range(3)
        ]
        # Music theory
        + [
            _make_spec(
                "western music theory",
                f"counterpoint composition {i}",
                "voice independence maps to module decoupling via interface contracts",
                f"fd-music-{i}",
            )
            for i in range(3)
        ]
        # Sailing
        + [
            _make_spec(
                "celestial navigation",
                f"sextant fix protocol {i}",
                "dead reckoning error maps to drift in iterative computation",
                f"fd-nav-{i}",
            )
            for i in range(3)
        ]
    )
    result = cluster_specs(specs, k=3, threshold=0.30, seed=42)
    assert result["status"] == "ok", f"got {result['status']}: {result.get('reason')}"
    assert result["k"] == 3
    assert all(s >= 3 for s in result["sizes"]), f"unbalanced: {result['sizes']}"
    assert min(result["pairwise_centroid_distances"].values()) >= 0.30


def test_homogeneous_specs_audit_returns_divergent_clusters_too_close():
    """9 specs all from biology → audit returns divergent_clusters_too_close."""
    specs = [
        _make_spec(
            "molecular biology",
            f"protein folding mechanism {i}",
            "enzyme catalysis maps to caching via reduced activation energy",
            f"fd-bio-{i}",
        )
        for i in range(9)
    ]
    result = cluster_specs(specs, k=3, threshold=0.30, seed=42)
    assert result["status"] == "divergent_clusters_too_close"
    assert "centroid distance" in result["reason"]
    # Should still return cluster data (so caller can log/debug), even when audit fails.
    # K may be 2 or 3 depending on whether degrade triggered first — the audit verdict
    # is what we care about, not the exact cluster count.
    assert len(result["clusters"]) == result["k"] >= 2


def test_seven_specs_three_domains_rebalances_to_min_three():
    """7 specs from 3 domains (3-2-2 distribution) → rebalance keeps clusters >= 3 by degrading K."""
    specs = (
        [
            _make_spec(
                "evolutionary biology",
                f"natural selection mechanism {i}",
                "fitness landscape maps to optimization surface",
                f"fd-bio-{i}",
            )
            for i in range(3)
        ]
        + [
            _make_spec(
                "western music theory",
                f"counterpoint {i}",
                "voice independence maps to module decoupling",
                f"fd-music-{i}",
            )
            for i in range(2)
        ]
        + [
            _make_spec(
                "celestial navigation",
                f"sextant fix {i}",
                "dead reckoning error maps to iterative drift",
                f"fd-nav-{i}",
            )
            for i in range(2)
        ]
    )
    result = cluster_specs(specs, k=3, threshold=0.30, seed=42)
    # Either rebalance succeeded at k=3, or we degraded to k=2 — both are acceptable outcomes
    # for a 3-2-2 distribution. Both must keep all clusters >= 3.
    assert all(s >= 3 for s in result["sizes"]), f"sizes={result['sizes']}"
    assert result["status"] in ("ok", "degraded_to_2_clusters")


def test_five_specs_two_domains_returns_degraded_to_2_clusters():
    """5 specs across 2 domains → returns degraded_to_2_clusters; downstream spawns 4 teammates."""
    specs = [
        _make_spec(
            "evolutionary biology",
            f"selection {i}",
            "fitness landscape maps to optimization",
            f"fd-bio-{i}",
        )
        for i in range(3)
    ] + [
        _make_spec(
            "western music theory",
            f"counterpoint {i}",
            "voice independence maps to decoupling",
            f"fd-music-{i}",
        )
        for i in range(2)
    ]
    result = cluster_specs(specs, k=3, threshold=0.20, seed=42)
    # k=3 with 5 specs and 3-2 split → cannot keep min_size=3 across 3 clusters → degrade to k=2
    assert result["status"] == "degraded_to_2_clusters"
    assert result["k"] == 2
    assert all(s >= 2 for s in result["sizes"])  # k=2, min_size enforced relative to feasibility


def test_empty_specs_returns_empty_status():
    result = cluster_specs([], k=3)
    assert result["status"] == "empty"
    assert result["k"] == 0
    assert result["clusters"] == []


def test_insufficient_specs_returns_status():
    """2 specs requested into k=3 → can't form 3 clusters."""
    specs = [
        _make_spec("biology", "x", "y", "fd-1"),
        _make_spec("music", "x", "y", "fd-2"),
    ]
    result = cluster_specs(specs, k=3)
    assert result["status"] == "insufficient_specs"
    assert result["k"] == 2  # falls back to one-cluster-per-spec


def test_real_brainstorm_corpus_clusters_above_threshold():
    """End-to-end: real adjacent + distant brainstorm specs cluster meaningfully."""
    adjacent = SPECS_DIR / "flux-explore-teams-brainstorm-adjacent.json"
    distant = SPECS_DIR / "flux-explore-teams-brainstorm-distant.json"
    if not adjacent.exists() or not distant.exists():
        pytest.skip("real brainstorm spec corpus not present (CI-only run?)")
    specs = json.loads(adjacent.read_text()) + json.loads(distant.read_text())
    result = cluster_specs(specs, k=3, threshold=0.20, seed=42)
    # Real corpus should produce ok or degraded — never insufficient or divergent
    assert result["status"] in ("ok", "degraded_to_2_clusters"), (
        f"unexpected status {result['status']}: {result.get('reason')} "
        f"sizes={result.get('sizes')} pairwise={result.get('pairwise_centroid_distances')}"
    )
    assert all(s >= 2 for s in result["sizes"])


def test_stderr_logs_centroid_distances_always(capsys):
    """P2 from plan review: always log centroid distances regardless of pass/fail."""
    specs = [
        _make_spec(f"domain-{i}", f"focus {i}", f"isom {i}", f"fd-{i}")
        for i in range(9)
    ]
    cluster_specs(specs, k=3, threshold=0.30, seed=42)
    captured = capsys.readouterr()
    assert "pairwise_centroid_distances" in captured.err
    assert "sizes" in captured.err
    assert "threshold" in captured.err
