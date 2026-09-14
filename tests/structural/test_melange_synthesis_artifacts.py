"""Pin the synthesis stage's artifact split in melange-workflow.js.

One synthesis agent used to be asked for four things in a single turn, largest
first: a 30+ KB markdown report, then `surfaced.jsonl`, then `run-manifest.json`,
then a three-field structured return. A live run (datum /
orthophoto-pass-and-address-gauge, 2026-09-13) stalled mid-turn immediately
after the big Write — the markdown landed at 20:18, the agent emitted nothing
for the next 6.5 minutes, and the two machine-readable artifacts and the
structured return never arrived. Because a stalled agent neither returns nor
throws, `dispatch()`'s catch could not degrade it and the workflow waited
indefinitely; it had to be killed by hand.

The shape that prevents it: three separate calls, cheapest-and-most-mechanical
first, none of them behind the long-form write.

  1. run-manifest.json — transcribed from controller state, independent of the
     synthesis agent, so the audit trail survives a synthesis that dies.
  2. {date}-synthesis.md — one artifact, one required return field.
  3. surfaced.jsonl — the eval target for scripts/_melange_score.py, extracted
     from the finished report by its own agent.

These are text assertions over the script, in the style of
test_melange_model_routing.py: the failure they guard is a live-run hazard and
the coupling is prose-to-code.
"""

import re
from pathlib import Path

import pytest

WORKFLOW_JS = (
    Path(__file__).resolve().parent.parent.parent
    / "skills"
    / "flux-melange-engine"
    / "workflow"
    / "melange-workflow.js"
)


@pytest.fixture(scope="module")
def src() -> str:
    return WORKFLOW_JS.read_text()


def _label_pos(src: str, label: str) -> int:
    m = re.search(rf'label: "{re.escape(label)}"', src)
    assert m, f'no agent labelled "{label}" in melange-workflow.js'
    return m.start()


def test_synthesis_stage_is_three_separate_agents(src):
    for label in ("run-manifest", "synthesis", "surfaced"):
        _label_pos(src, label)


def test_manifest_is_written_before_the_long_form_report(src):
    """The audit trail must not sit behind the artifact that stalled."""
    assert _label_pos(src, "run-manifest") < _label_pos(src, "synthesis"), (
        "run-manifest.json is dispatched after the synthesis markdown — it is "
        "script-derived and must land first so it survives a dead synthesis"
    )
    assert _label_pos(src, "synthesis") < _label_pos(src, "surfaced")


def test_synthesis_prompt_asks_for_exactly_one_artifact(src):
    start = src.index('`You are writing the synthesis for a flux-melange')
    end = src.index('label: "synthesis"', start)
    prompt = src[start:end]
    assert "SCOPE — this is your ONLY artifact" in prompt
    assert "Do not write surfaced.jsonl" in prompt
    assert "ALSO write" not in prompt and "AND write" not in prompt, (
        "the synthesis prompt still chains extra artifacts onto the long-form "
        "write — that ordering is what lost surfaced.jsonl and run-manifest.json"
    )


def test_synthesis_return_schema_is_minimal(src):
    m = re.search(
        r"const SYNTH_SCHEMA = \{\s*type: \"object\",\s*required: \[([^\]]*)\]",
        src,
    )
    assert m, "SYNTH_SCHEMA not found"
    required = re.findall(r'"([^"]+)"', m.group(1))
    assert required == ["top_finding"], (
        f"SYNTH_SCHEMA requires {required}; only top_finding may be required — "
        "synthesis_path is script-known and surfaced_count belongs to the "
        "surfacing agent, so neither may gate the synthesis agent's return"
    )


def test_manifest_is_derived_from_controller_state_not_from_the_agent(src):
    """The scribe transcribes; it never re-derives the manifest from a prompt dump."""
    start = src.index("const manifestJson = JSON.stringify(")
    end = src.index('label: "run-manifest"', start)
    block = src[start:end]
    for field in (
        "gain_history: R.gainHistory",
        "spice_trail: R.spiceTrail",
        "directive_history",
        "halt_reason: R.haltReason",
    ):
        assert field in block, f"manifest loses {field} from controller state"
    assert "Transcription task" in block and "verbatim" in block


def test_surfacing_recovers_a_report_whose_agent_died_after_writing_it(src):
    """Writing the report and returning from it are separate failures now."""
    assert '"report_found"' in src, "SURFACED_SCHEMA lost report_found"
    assert "const reportOnDisk" in src
    assert "R.synthesisPath = synth || reportOnDisk ? synthesisPath : null;" in src, (
        "a synthesis that wrote its report and then died on the structured "
        "return must still count as a complete, scoreable run"
    )
    # The surfacing call must not be nested under `if (synth)`.
    surfaced_at = _label_pos(src, "surfaced")
    guard = src.rfind("if (synth)", 0, surfaced_at)
    synth_at = _label_pos(src, "synthesis")
    assert guard < synth_at, "the surfacing stage is gated on the synthesis return"


def test_report_reports_missing_artifacts_instead_of_zero(src):
    """surfaced_count must be null when unknown — 0 would read as 'surfaced nothing'."""
    assert "surfaced_count: primary.surfacedCount" in src
    assert "primary.synth.surfaced_count" not in src
    assert "R.artifactCaveats.push" in src, (
        "a missing surfaced.jsonl / run-manifest.json must reach the report's "
        "caveats, not vanish"
    )


def test_no_dangling_references_to_the_old_synth_fields(src):
    for stale in ("synth.synthesis_path", "synth.surfaced_count"):
        assert stale not in src, (
            f"{stale} survives — the synthesis agent no longer returns it"
        )
