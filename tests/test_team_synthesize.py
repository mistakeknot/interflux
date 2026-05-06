"""Unit tests for team_synthesize.py.

Run: python3 -m pytest interverse/interflux/tests/test_team_synthesize.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from team_synthesize import (  # noqa: E402
    _audit_blind_r1,
    _build_orchestrator_prompt,
    _cost_preview,
    _extract_member_session_ids,
    _slug_from_target,
    _validate_synthesis,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SPECS_GLOB = str(REPO_ROOT / ".claude" / "flux-gen-specs" / "flux-explore-teams-brainstorm-*.json")


def test_slug_basic():
    assert _slug_from_target("Cross-Domain Debate Synthesis") == "cross-domain-debate-synthesis"


def test_slug_truncates():
    assert len(_slug_from_target("a" * 200)) <= 60


def test_slug_handles_punctuation():
    assert _slug_from_target("foo, bar! baz?") == "foo-bar-baz"


def test_validate_synthesis_pass():
    content = """# Title
## Cross-Domain Isomorphism 1: A
detail
## Cross-Domain Isomorphism 2: B
detail
## Cross-Domain Isomorphism 3: C
detail
## Unresolved Tensions
notes
"""
    result = _validate_synthesis(content)
    assert result["passed"] is True
    assert result["isomorphism_section_count"] == 3
    assert result["has_unresolved_tensions"] is True
    assert result["issues"] == []


def test_validate_synthesis_too_few_isoms():
    content = """## Cross-Domain Isomorphism 1: A
## Unresolved Tensions
notes
"""
    result = _validate_synthesis(content)
    assert not result["passed"]
    assert "expected ≥3" in result["issues"][0]


def test_validate_synthesis_missing_unresolved():
    content = """## Cross-Domain Isomorphism 1: A
## Cross-Domain Isomorphism 2: B
## Cross-Domain Isomorphism 3: C
"""
    result = _validate_synthesis(content)
    assert not result["passed"]
    assert any("Unresolved Tensions" in i for i in result["issues"])


def test_audit_blind_r1_clean():
    transcript = """[ts1] lead → debater-cluster-0: Round 1 begin
[ts2] debater-cluster-0 → lead: candidate
[ts3] debater-cluster-1 → lead: candidate
[ts4] lead → questioner: Round 1.5 open
[ts5] debater-cluster-0 → debater-cluster-1: cross-talk during R2 is ok
"""
    result = _audit_blind_r1(transcript)
    assert result["passed"] is True
    assert result["violations"] == []


def test_audit_blind_r1_contamination():
    transcript = """[ts1] lead → debater-cluster-0: Round 1 begin
[ts2] debater-cluster-0 → debater-cluster-1: I'll show you my candidate
[ts3] debater-cluster-1 → lead: candidate
[ts4] lead → questioner: Round 1.5 open
"""
    result = _audit_blind_r1(transcript)
    assert not result["passed"]
    assert len(result["violations"]) == 1
    assert "debater-cluster-0 → debater-cluster-1" in result["violations"][0]


def test_audit_blind_r1_substring_in_body_does_not_flip_state():
    """A debater body line that mentions 'round 2' must not flip OFF the in_round_1 state.

    Round transitions are only flipped by a LEAD control line — body text from any
    non-lead sender that contains 'round 2' is just a substring, not a control event.
    """
    transcript = """[ts1] lead → debater-cluster-0: Round 1: begin posting candidates
[ts2] debater-cluster-0 → lead: my candidate references the round 2 mechanism from spec X
[ts3] debater-cluster-0 → debater-cluster-1: peeking at your work (CONTAMINATION)
[ts4] lead → questioner: Round 1.5: open visibility
"""
    result = _audit_blind_r1(transcript)
    # The cross-debater message at ts3 is during Round 1 — must be flagged
    assert not result["passed"], f"got passed=True with violations={result['violations']}"
    assert any("debater-cluster-0 → debater-cluster-1" in v for v in result["violations"])


def test_audit_blind_r1_round_15_disables_state():
    transcript = """[ts1] lead → debater-cluster-0: Round 1: begin
[ts2] lead → questioner: Round 1.5: open visibility
[ts3] debater-cluster-0 → debater-cluster-1: cross-talk now allowed
"""
    result = _audit_blind_r1(transcript)
    # ts3 is after Round 1.5 transition → must NOT be a violation
    assert result["passed"], f"got violations={result['violations']}"


def test_cost_preview_calculation():
    # 5 teammates × 2 rounds × $0.30 = $3.00
    p = _cost_preview(team_size=5, rounds=2, per_session_cost_usd=0.30)
    assert p["estimated_total_usd"] == 3.0
    assert p["team_size"] == 5
    assert p["rounds"] == 2


def test_extract_member_session_ids_handles_variant_keys():
    cfg = {
        "members": [
            {"name": "a", "session_id": "s-1"},
            {"name": "b", "agent_id": "s-2"},
            {"name": "c", "id": "s-3"},
            {"name": "d"},  # no id
        ]
    }
    ids = _extract_member_session_ids(cfg)
    assert ids == ["s-1", "s-2", "s-3"]


def test_extract_member_session_ids_no_members():
    assert _extract_member_session_ids({}) == []


def test_extract_session_ids_observed_live_schema():
    """Schema observed in claude 2.1.122 — leadSessionId at top, agentId per member as
    name token (NOT a UUID). Lead UUID extracted; member name tokens skipped (the parser
    only picks up keys that could plausibly be UUIDs)."""
    cfg = {
        "name": "teams-test-3b",
        "leadSessionId": "bcc6a665-591e-4d5b-9879-f3fca477f74a",
        "members": [
            {
                "agentId": "team-lead@teams-test-3b",
                "name": "team-lead",
                "model": "claude-sonnet-4-6",
            },
            {
                "agentId": "alice@teams-test-3b",
                "name": "alice",
                "model": "sonnet",
            },
            {
                "agentId": "bob@teams-test-3b",
                "name": "bob",
                "model": "sonnet",
            },
        ],
    }
    ids = _extract_member_session_ids(cfg)
    # Only the lead UUID is extractable; agentId values are name tokens, not session ids
    assert ids == ["bcc6a665-591e-4d5b-9879-f3fca477f74a"]


def test_extract_session_ids_forward_compat_with_runtime_sessionId():
    """If a future claude version adds runtime `sessionId` to each member, pick it up."""
    cfg = {
        "leadSessionId": "lead-uuid",
        "members": [
            {"agentId": "alice@team", "sessionId": "alice-uuid"},
            {"agentId": "bob@team", "sessionId": "bob-uuid"},
        ],
    }
    ids = _extract_member_session_ids(cfg)
    assert ids == ["lead-uuid", "alice-uuid", "bob-uuid"]


def test_orchestrator_prompt_contains_required_protocol_elements():
    cluster_result = {
        "k": 3,
        "clusters": [
            {
                "index": i,
                "specs": [
                    {"name": f"fd-x-{i}-{j}", "source_domain": f"domain-{i}", "expected_isomorphisms": "iso"}
                    for j in range(3)
                ],
            }
            for i in range(3)
        ],
    }
    prompt = _build_orchestrator_prompt(
        target="x",
        slug="test-slug",
        cluster_result=cluster_result,
        rounds=2,
        transcript_dir=Path("/tmp/x"),
        final_synthesis_path=Path("/tmp/x.md"),
    )
    # Discipline rules must appear
    assert "MESH MAILBOX" in prompt
    assert "PATH-ONLY HANDOFF" in prompt
    assert "BLIND" in prompt
    assert "REPLIES FIRST" in prompt
    # TaskCreated cap (per F1.2 verdict)
    assert "TaskCreated" in prompt
    # Author teammate
    assert "author-test-slug" in prompt
    # Three debater clusters referenced
    assert "Cluster 0" in prompt and "Cluster 1" in prompt and "Cluster 2" in prompt


def test_prepare_smoke_via_cli(tmp_path):
    """End-to-end: prepare returns ready envelope when given the real brainstorm corpus."""
    if not list(REPO_ROOT.glob(".claude/flux-gen-specs/flux-explore-teams-brainstorm-*.json")):
        pytest.skip("real spec corpus not present")
    output = tmp_path / "synth.md"
    transcript_dir = tmp_path / "transcript"
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "team_synthesize.py"),
        "prepare",
        "--target",
        "smoke target",
        "--slug",
        "smoke",
        "--specs-glob",
        SPECS_GLOB,
        "--output",
        str(output),
        "--transcript-dir",
        str(transcript_dir),
        "--threshold",
        "0.20",
        "--seed",
        "42",
        "--preview-sleep-override",
        "0",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "ready"
    assert envelope["team_size"] == 6  # 3 debaters + author + questioner = 5; +1 for author/questioner == 2+3+1 = 6
    assert (transcript_dir / "orchestrator-spawn-prompt.md").exists()


def test_prepare_returns_fallback_for_homogeneous_specs(tmp_path):
    """When clusters are too close, prepare exits 1 with fallback envelope."""
    homog_spec = tmp_path / "homog.json"
    homog_spec.write_text(
        json.dumps(
            [
                {
                    "name": f"fd-{i}",
                    "source_domain": "biology",
                    "focus": f"focus {i}",
                    "expected_isomorphisms": "iso",
                }
                for i in range(9)
            ]
        )
    )
    output = tmp_path / "synth.md"
    transcript_dir = tmp_path / "transcript"
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "team_synthesize.py"),
        "prepare",
        "--target",
        "homog",
        "--slug",
        "homog",
        "--specs-glob",
        str(homog_spec),
        "--output",
        str(output),
        "--transcript-dir",
        str(transcript_dir),
        "--threshold",
        "0.30",
        "--seed",
        "42",
        "--preview-sleep-override",
        "0",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "fallback"
    assert envelope["fallback_reason"] == "divergent_clusters"
