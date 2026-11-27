"""Tests for scripts/cross_track_convergence.py (issue #52, finding C-4).

Cross-track convergence used to be ranked by raw track head-count. Track agents
usually share one base model family, so that agreement is correlated error, not
independent corroboration. These tests pin the family-weighted replacement.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "cross_track_convergence.py"
TRACK_SYNTHESIS = (ROOT / "skills" / "flux-review-engine" / "phases" / "track-synthesis.md").read_text()
SPEC = (ROOT / "docs" / "spec" / "core" / "synthesis.md").read_text()

sys.path.insert(0, str(ROOT / "scripts"))
import cross_track_convergence as ctc  # noqa: E402


def _track(review: Path, letter: str, agent_families: dict[str, str], with_provenance=True):
    d = review / f"track-{letter}"
    d.mkdir(parents=True)
    findings = []
    for i, (agent, fam) in enumerate(agent_families.items(), 1):
        f = {"id": f"P1-{i}", "severity": "P1", "agents": [agent], "title": "t"}
        if with_provenance:
            f["provenance"] = {agent: {"provider": "x", "model_family": fam, "model_id": "m"}}
        findings.append(f)
    (d / "findings.json").write_text(json.dumps({"findings": findings, "verdict": "needs-changes"}))


def _sidecar(review: Path, clusters: list[dict]):
    (review / "cross-track-convergence.json").write_text(json.dumps({"clusters": clusters}))


def _cluster(cid: str, tracks: dict[str, str]) -> dict:
    return {"id": cid, "title": f"finding {cid}",
            "tracks": {t: [{"agent": a, "finding_id": "P1-1"}] for t, a in tracks.items()}}


def _run(review: Path, *args):
    return subprocess.run([sys.executable, str(SCRIPT), str(review), "--json", *args],
                          capture_output=True, text=True)


def _score(review: Path) -> dict:
    r = _run(review)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.fixture
def single_family(tmp_path):
    for letter, agent in (("a", "fd-a1"), ("b", "fd-b1"), ("c", "fd-c1")):
        _track(tmp_path, letter, {agent: "claude"})
    _sidecar(tmp_path, [_cluster("XT-1", {"a": "fd-a1", "b": "fd-b1", "c": "fd-c1"})])
    return tmp_path


@pytest.fixture
def mixed_family(tmp_path):
    _track(tmp_path, "a", {"fd-a1": "claude"})
    _track(tmp_path, "c", {"fd-c1": "deepseek"})
    _sidecar(tmp_path, [_cluster("XT-1", {"a": "fd-a1", "c": "fd-c1"})])
    return tmp_path


class TestSingleFamily:
    def test_three_of_three_same_family_is_correlated_not_high(self, single_family):
        res = _score(single_family)
        c = res["clusters"][0]
        assert c["raw_tracks"] == 3
        assert c["model_families"] == ["claude"]
        assert c["confidence"] == "Correlated"
        assert c["confidence"] != "High"
        # N same-family tracks ~= 1 source + modest bonus, well below raw count.
        assert c["weighted_convergence"] == pytest.approx(1.5)
        assert c["weighted_convergence"] < c["raw_tracks"]

    def test_caveat_emitted(self, single_family):
        res = _score(single_family)
        assert res["single_family"] is True
        assert res["caveat"] and "correlated" in res["caveat"].lower()
        assert "claude" in res["caveat"]

    def test_caveat_and_label_written_into_synthesis(self, single_family):
        syn = single_family / "2026-11-26-synthesis.md"
        syn.write_text("# S\n\n## Cross-Track Convergence\n\nXT-1 prose\n\n## Domain-Expert Insights (Track A)\n")
        r = _run(single_family, "--write-synthesis", str(syn))
        assert r.returncode == 0, r.stderr
        text = syn.read_text()
        assert ctc.BEGIN in text and ctc.END in text
        assert "Caveat - correlated convergence" in text
        block = text.split(ctc.BEGIN)[1].split(ctc.END)[0]
        assert "| XT-1 |" in block and "| Correlated |" in block and "| High |" not in block
        # Block lands under the convergence heading, before the next section.
        assert text.index(ctc.BEGIN) > text.index("## Cross-Track Convergence")
        assert text.index(ctc.END) < text.index("## Domain-Expert Insights")
        # Idempotent: re-running replaces rather than duplicates.
        _run(single_family, "--write-synthesis", str(syn))
        assert syn.read_text().count(ctc.BEGIN) == 1

    def test_missing_provenance_never_adds_independence(self, tmp_path):
        _track(tmp_path, "a", {"fd-a1": "claude"}, with_provenance=False)
        _track(tmp_path, "c", {"fd-c1": "claude"}, with_provenance=False)
        _sidecar(tmp_path, [_cluster("XT-1", {"a": "fd-a1", "c": "fd-c1"})])
        c = _score(tmp_path)["clusters"][0]
        assert c["model_families"] == ["claude"]
        assert c["confidence"] == "Correlated"
        assert sorted(c["family_unresolved"]) == ["a:fd-a1", "c:fd-c1"]

    def test_sidecar_family_claims_are_ignored(self, single_family):
        sc = json.loads((single_family / "cross-track-convergence.json").read_text())
        sc["clusters"][0]["tracks"]["c"][0]["model_family"] = "deepseek"
        (single_family / "cross-track-convergence.json").write_text(json.dumps(sc))
        assert _score(single_family)["clusters"][0]["confidence"] == "Correlated"


class TestMixedFamily:
    def test_cross_family_gets_full_credit(self, mixed_family):
        res = _score(mixed_family)
        c = res["clusters"][0]
        assert c["model_families"] == ["claude", "deepseek"]
        # Cross-family agreement: each family counts as a full source, with the
        # single-run 1.5x multiplier on the second family.
        assert c["weighted_convergence"] == pytest.approx(1 + 1.5)
        assert c["weighted_convergence"] >= c["raw_tracks"]
        assert c["confidence"] == "High"
        assert res["single_family"] is False
        assert res["caveat"] is None

    def test_partial_mix_ranks_above_single_family(self, tmp_path):
        _track(tmp_path, "a", {"fd-a1": "claude", "fd-a2": "claude"})
        _track(tmp_path, "b", {"fd-b1": "claude"})
        _track(tmp_path, "c", {"fd-c1": "deepseek", "fd-c2": "claude"})
        _sidecar(tmp_path, [
            {"id": "XT-1", "title": "same family",
             "tracks": {"a": [{"agent": "fd-a1"}], "b": [{"agent": "fd-b1"}],
                        "c": [{"agent": "fd-c2"}]}},
            {"id": "XT-2", "title": "mixed",
             "tracks": {"a": [{"agent": "fd-a2"}], "c": [{"agent": "fd-c1"}]}},
        ])
        res = _score(tmp_path)
        by_id = {c["id"]: c for c in res["clusters"]}
        assert by_id["XT-1"]["confidence"] == "Correlated"
        assert by_id["XT-2"]["confidence"] == "High"
        # Ranked by weighted convergence, not raw count: 2-track mixed beats 3-track same-family.
        assert [c["id"] for c in res["clusters"]] == ["XT-2", "XT-1"]
        assert res["single_family"] is False

    def test_flat_model_family_field_is_read(self, tmp_path):
        for letter, agent, fam in (("a", "fd-a1", "claude"), ("c", "fd-c1", "qwen")):
            d = tmp_path / f"track-{letter}"
            d.mkdir()
            (d / "findings.json").write_text(json.dumps({"findings": [
                {"id": "P1-1", "agent": agent, "model_family": fam}]}))
        _sidecar(tmp_path, [_cluster("XT-1", {"a": "fd-a1", "c": "fd-c1"})])
        assert _score(tmp_path)["clusters"][0]["model_families"] == ["claude", "qwen"]


class TestWeighting:
    CFG = dict(ctc.DEFAULTS)

    def test_single_family_never_reaches_high(self):
        for n in range(2, 5):
            w = ctc.weigh({"claude": {str(i) for i in range(n)}}, self.CFG)
            assert w < self.CFG["high_threshold"]
            assert ctc.label(n, 1, w, self.CFG) == "Correlated"

    def test_reuses_single_run_cross_family_multiplier(self):
        # Spec Step 4 example shape: 2 claude + 1 deepseek.
        w = ctc.weigh({"claude": {"a", "b"}, "deepseek": {"c"}}, self.CFG)
        assert w == pytest.approx(1.25 + 1.5)
        assert self.CFG["cross_family_weight"] == 1.5

    def test_single_track_is_not_convergent(self, tmp_path):
        _track(tmp_path, "a", {"fd-a1": "claude"})
        _sidecar(tmp_path, [_cluster("XT-1", {"a": "fd-a1"})])
        res = _score(tmp_path)
        assert res["convergent_count"] == 0
        assert res["clusters"][0]["confidence"] == "Single-track"

    def test_config_loaded_from_defaults_yaml(self):
        cfg = ctc.load_config(None)
        for k in ctc.DEFAULTS:
            assert k in cfg
        assert cfg["cross_family_weight"] == 1.5

    def test_missing_sidecar_exits_2(self, tmp_path):
        assert _run(tmp_path).returncode == 2


class TestContract:
    def test_track_synthesis_invokes_script(self):
        assert "scripts/cross_track_convergence.py" in TRACK_SYNTHESIS
        assert "cross-track-convergence.json" in TRACK_SYNTHESIS

    def test_track_synthesis_forbids_raw_count_ranking(self):
        assert "Rank convergent findings by convergence score (more tracks = higher confidence)" not in TRACK_SYNTHESIS
        assert "Do NOT assign a confidence label" in TRACK_SYNTHESIS
        assert "model_family" in TRACK_SYNTHESIS
        assert "issue #52" in TRACK_SYNTHESIS

    def test_spec_documents_cross_track_weighting(self):
        assert "Step 4b: Cross-Track Convergence Weighting" in SPEC
        assert "Correlated" in SPEC
        assert "same_family_track_bonus" in SPEC
