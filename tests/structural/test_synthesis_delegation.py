"""Conformance check for the Synthesis Delegation contract.

Guards against silent drift between:
  - docs/spec/contracts/synthesis-delegation.md  (the contract)
  - skills/flux-engine/phases/synthesize.md       (the host call sites)
  - docs/spec/core/synthesis.md                   (the spec output schema)

Asserts:
  (a) the contract's documented input params are a superset of what the
      review/research call sites actually pass on the wire;
  (b) the documented review output filename is summary.md and research is
      synthesis.md, consistently across the contract, the spec, and the phase
      file (resolves the summary.md/synthesis.md collision);
  (c) the protocol version + degraded fallback are present on the wire and in
      the contract (so the version stamp and fallback can't silently vanish).

Self-contained: reads files by path, no dependency on the shared structural
fixtures (which currently target an older skill layout).
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "docs" / "spec" / "contracts" / "synthesis-delegation.md"
PHASE = REPO / "skills" / "flux-engine" / "phases" / "synthesize.md"
SPEC_SYNTH = REPO / "docs" / "spec" / "core" / "synthesis.md"
README = REPO / "docs" / "spec" / "README.md"

PROTOCOL_VERSION = "1.0"
DEGRADED_LABEL = "degraded synthesis — intersynth unavailable"


def _call_site_params(text: str, agent: str) -> set[str]:
    """Extract KEY=... param names from a `Task(intersynth:<agent>)` prompt block."""
    # Find the fenced block that contains the Task() invocation for this agent.
    marker = f"Task(intersynth:{agent})"
    idx = text.index(marker)
    block = text[idx : text.index("```", idx)]
    # Param lines look like `    KEY=...` or `    KEY="..."`.
    keys = set(re.findall(r"^\s*([A-Z_]+)=", block, flags=re.MULTILINE))
    return keys


def test_files_exist():
    for p in (CONTRACT, PHASE, SPEC_SYNTH, README):
        assert p.exists(), f"missing {p}"


def test_contract_registered_in_readme():
    readme = README.read_text(encoding="utf-8")
    assert "contracts/synthesis-delegation.md" in readme, (
        "synthesis-delegation.md not registered in docs/spec/README.md"
    )


def test_review_call_site_passes_documented_inputs():
    """Review call site MUST pass protocol version, OUTPUT_DIR, MODE,
    CONTEXT, and PROTECTED_PATHS (the prior drift was PROTECTED_PATHS)."""
    phase = PHASE.read_text(encoding="utf-8")
    passed = _call_site_params(phase, "synthesize-review")
    required = {
        "SYNTHESIS_PROTOCOL_VERSION",
        "OUTPUT_DIR",
        "VERDICT_LIB",
        "MODE",
        "CONTEXT",
        "PROTECTED_PATHS",
    }
    missing = required - passed
    assert not missing, f"review call site missing required params: {missing}"


def test_research_call_site_passes_documented_inputs():
    phase = PHASE.read_text(encoding="utf-8")
    passed = _call_site_params(phase, "synthesize-research")
    required = {
        "SYNTHESIS_PROTOCOL_VERSION",
        "OUTPUT_DIR",
        "VERDICT_LIB",
        "RESEARCH_QUESTION",
        "QUERY_TYPE",
        "ESTIMATED_DEPTH",
    }
    missing = required - passed
    assert not missing, f"research call site missing required params: {missing}"


def test_contract_documents_call_site_params():
    """The contract input table MUST be a superset of what each call site passes."""
    phase = PHASE.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    for agent in ("synthesize-review", "synthesize-research"):
        for param in _call_site_params(phase, agent):
            assert param in contract, (
                f"{agent} passes {param} but the contract does not document it"
            )


def test_review_output_filename_is_summary_md():
    """Review mode writes summary.md, consistently across contract + spec + phase."""
    contract = CONTRACT.read_text(encoding="utf-8")
    spec = SPEC_SYNTH.read_text(encoding="utf-8")
    phase = PHASE.read_text(encoding="utf-8")

    # Contract output table names summary.md as the review report file.
    assert "`{OUTPUT_DIR}/summary.md`" in contract
    # Spec Step 7 writes summary.md.
    assert "{OUTPUT_DIR}/summary.md" in spec
    # Phase review block writes summary.md (not synthesis.md).
    assert "It writes `{OUTPUT_DIR}/summary.md` and `{OUTPUT_DIR}/findings.json`" in phase


def test_research_output_filename_is_synthesis_md():
    contract = CONTRACT.read_text(encoding="utf-8")
    phase = PHASE.read_text(encoding="utf-8")
    assert "`{OUTPUT_DIR}/synthesis.md`" in contract
    # Phase research block writes synthesis.md.
    assert "It writes `{OUTPUT_DIR}/synthesis.md`" in phase


def test_protocol_version_on_the_wire():
    phase = PHASE.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    assert f"SYNTHESIS_PROTOCOL_VERSION={PROTOCOL_VERSION}" in phase, (
        "host call sites must carry SYNTHESIS_PROTOCOL_VERSION on the wire"
    )
    assert f"`{PROTOCOL_VERSION}`" in contract


def test_degraded_fallback_present_and_labeled():
    """The mandatory degraded fallback must exist in both contract and phase,
    with the exact non-silent label."""
    contract = CONTRACT.read_text(encoding="utf-8")
    phase = PHASE.read_text(encoding="utf-8")
    assert DEGRADED_LABEL in contract, "contract missing degraded-synthesis label"
    assert DEGRADED_LABEL in phase, "phase file missing degraded-synthesis label"
    assert "Degraded Host Fallback" in phase, "phase file missing Step 3.2a fallback"
