"""Integration coverage for flux-melange per-run cost artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "scripts" / "melange-costs.py"
WORKFLOW = (
    ROOT / "skills" / "flux-melange-engine" / "workflow" / "melange-workflow.js"
)


def test_melange_standard_profile_is_balanced_three_rounds() -> None:
    defaults = yaml.safe_load(
        (ROOT / "config" / "flux-melange" / "defaults.yaml").read_text()
    )
    assert defaults["quality"] == "balanced"
    assert defaults["weights"] == "balanced"
    assert defaults["max_rounds"] == 3


def _transcript(path: Path, marker: dict, *, model: str, usage: dict) -> None:
    rows = [
        {
            "message": {
                "role": "user",
                "content": (
                    "<flux-melange-cost>"
                    + json.dumps(marker, separators=(",", ":"))
                    + "</flux-melange-cost>\nReview the target."
                ),
            }
        },
        {
            "message": {
                "role": "assistant",
                "model": model,
                "usage": usage,
            }
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _run_hook(transcript: Path) -> None:
    subprocess.run(
        [sys.executable, str(CAPTURE), "hook"],
        input=json.dumps(
            {
                "hook_event_name": "SubagentStop",
                "session_id": "parent-session",
                "transcript_path": str(transcript.with_name("parent.jsonl")),
                "agent_id": transcript.stem,
                "agent_transcript_path": str(transcript),
            }
        ),
        text=True,
        check=True,
        cwd=ROOT,
    )


def test_melange_run_writes_per_agent_and_per_round_cost_summary(tmp_path: Path) -> None:
    output_dir = tmp_path / "run"
    output_dir.mkdir()

    seed = tmp_path / "seed.jsonl"
    _transcript(
        seed,
        {
            "output_dir": str(output_dir),
            "runtime": "claude",
            "agent": "seed:adjacent",
            "round": "round-0",
            "backend": "claude",
            "model": "sonnet",
            "quota_source": "unknown",
        },
        model="claude-sonnet-5",
        usage={
            "input_tokens": 100,
            "cache_creation_input_tokens": 25,
            "cache_read_input_tokens": 50,
            "output_tokens": 20,
        },
    )
    probe = tmp_path / "probe.jsonl"
    _transcript(
        probe,
        {
            "output_dir": str(output_dir),
            "runtime": "claude",
            "agent": "probe:r1:deepen",
            "round": "round-1",
            "backend": "claude",
            "model": "sonnet",
            "quota_source": "subscription",
        },
        model="claude-sonnet-5",
        usage={"input_tokens": 80, "output_tokens": 30},
    )

    _run_hook(seed)
    _run_hook(probe)

    summary_path = output_dir / "cost-summary.json"
    assert summary_path.exists(), "a melange run must write its cost summary"
    summary = json.loads(summary_path.read_text())

    assert [agent["agent"] for agent in summary["agents"]] == [
        "seed:adjacent",
        "probe:r1:deepen",
    ]
    assert [agent["agent_id"] for agent in summary["agents"]] == ["seed", "probe"]
    assert summary["agents"][0] | {
        "tokens_in": 175,
        "tokens_out": 20,
        "backend": "claude",
        "model": "claude-sonnet-5",
        "quota_source": "unknown",
    } == summary["agents"][0]
    assert summary["rounds"] == [
        {
            "round": "round-0",
            "agent_count": 1,
            "tokens_in": 175,
            "tokens_out": 20,
        },
        {
            "round": "round-1",
            "agent_count": 1,
            "tokens_in": 80,
            "tokens_out": 30,
        },
    ]
    assert summary["totals"] == {
        "agent_count": 2,
        "tokens_in": 255,
        "tokens_out": 50,
    }
    assert (output_dir / "cost-summary.md").exists()


def test_subagent_stop_hook_registers_cost_capture() -> None:
    hooks = json.loads((ROOT / ".claude-plugin" / "hooks" / "hooks.json").read_text())
    registered = hooks["hooks"]["SubagentStop"]
    commands = [
        hook["command"]
        for group in registered
        for hook in group["hooks"]
        if hook["type"] == "command"
    ]
    assert commands == [
        "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/melange-costs.py hook"
    ]


def test_every_workflow_agent_dispatch_carries_a_cost_marker() -> None:
    source = WORKFLOW.read_text()
    dispatch = source[
        source.index("async function dispatch(") : source.index("// ---- schemas")
    ]
    assert "<flux-melange-cost>" in dispatch
    assert "output_dir: R.base" in dispatch
    assert "agent: opts.label" in dispatch
    assert "round: opts.costRound" in dispatch
    assert "quota_source:" in dispatch
    assert "external_backend:" in dispatch
    assert "external_model:" in dispatch
    assert source.count("await agent(") == 2, (
        "all workflow calls must pass through dispatch(); only its primary and shim "
        "agent() calls may remain direct"
    )


def test_peer_marker_keeps_external_backend_visible_when_usage_is_unknown(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    transcript = tmp_path / "shim.jsonl"
    _transcript(
        transcript,
        {
            "output_dir": str(output_dir),
            "runtime": "codex",
            "agent": "probe:r1:deepen",
            "round": "round-1",
            "backend": "claude",
            "model": "haiku",
            "quota_source": "unknown",
            "external_backend": "codex",
            "external_model": "gpt-5.6-sol",
            "external_quota_source": "unknown",
        },
        model="claude-haiku-4-5",
        usage={"input_tokens": 40, "output_tokens": 10},
    )

    _run_hook(transcript)

    summary = json.loads((output_dir / "cost-summary.json").read_text())
    assert [(row["backend"], row["model"]) for row in summary["agents"]] == [
        ("claude", "claude-haiku-4-5"),
        ("codex", "gpt-5.6-sol"),
    ]
    assert summary["agents"][1]["tokens_in"] is None
    assert summary["agents"][1]["tokens_out"] is None
    assert summary["agents"][1]["usage_status"] == "unknown"
    assert summary["totals"]["unknown_usage_count"] == 1
