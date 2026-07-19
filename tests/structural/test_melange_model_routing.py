"""Pin melange-workflow.js model routing to the documented quality table.

The routing spec lives in prose (skills/flux-melange-engine/references/
budget-ladder.md § Quality → model routing) and in code (the MODEL block in
workflow/melange-workflow.js). Drift between them is a live-run hazard, not a
cosmetic one: routing the assayer to opus under balanced fed a findings-JSON
prompt to opus-scale thinking and tripped the host's no-progress watchdog,
killing a 2.2-hour run (Sylveste-kp9). This test hard-codes the documented
table; changing routing on purpose means updating budget-ladder.md, the MODEL
block, and this table together.
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

# budget-ladder.md § Quality → model routing (loop steps), plus the parley
# additions (shim/advocate/moderator) pinned to their intended values.
EXPECTED = {
    "designAdjacent": {"economy": "sonnet", "balanced": "sonnet", "max": "opus"},
    "designDistant": {"economy": "sonnet", "balanced": "opus", "max": "opus"},
    "probe": {"economy": "sonnet", "balanced": "sonnet", "max": "opus"},
    "fusedDesign": {"economy": "sonnet", "balanced": "opus", "max": "opus"},
    "assay": {"economy": "sonnet", "balanced": "sonnet", "max": "opus"},
    "verify": {"economy": "haiku", "balanced": "sonnet", "max": "sonnet"},
    "synthesis": {"economy": "sonnet", "balanced": "opus", "max": "opus"},
    "shim": {"economy": "haiku", "balanced": "haiku", "max": "haiku"},
    "advocate": {"economy": "sonnet", "balanced": "opus", "max": "opus"},
    "moderator": {"economy": "sonnet", "balanced": "opus", "max": "opus"},
}

QUALITIES = ("economy", "balanced", "max")


def _parse_model_block(src: str) -> dict[str, dict[str, str]]:
    """Evaluate the MODEL object's ternaries for each quality tier."""
    block_m = re.search(r"const MODEL = \{(.*?)\n\};", src, re.DOTALL)
    assert block_m, "MODEL block not found in melange-workflow.js"
    block = block_m.group(1)

    routing: dict[str, dict[str, str]] = {}
    ternary = re.compile(
        r'(\w+):\s*Q === "(economy|balanced|max)"\s*\?\s*"(\w+)"\s*:\s*"(\w+)"'
    )
    constant = re.compile(r'(\w+):\s*"(\w+)"\s*,')
    for key, q, then_m, else_m in ternary.findall(block):
        routing[key] = {
            quality: then_m if quality == q else else_m for quality in QUALITIES
        }
    for key, model in constant.findall(block):
        routing.setdefault(key, {q: model for q in QUALITIES})
    return routing


@pytest.fixture(scope="module")
def workflow_src() -> str:
    return WORKFLOW_JS.read_text()


def test_model_routing_matches_documented_table(workflow_src):
    routing = _parse_model_block(workflow_src)
    assert set(routing) == set(EXPECTED), (
        f"MODEL keys drifted: missing={set(EXPECTED) - set(routing)}, "
        f"unexpected={set(routing) - set(EXPECTED)} — update budget-ladder.md "
        "and this table together"
    )
    for key, expected in EXPECTED.items():
        assert routing[key] == expected, (
            f"MODEL.{key} routes {routing[key]}, documented table says "
            f"{expected} (budget-ladder.md § Quality → model routing)"
        )


def test_dispatch_degrades_agent_failures_to_null(workflow_src):
    """A stalled/thrown agent must degrade to null, never kill the run."""
    fn_m = re.search(
        r"async function dispatch\(.*?\n\}", workflow_src, re.DOTALL
    )
    assert fn_m, (
        "dispatch() must be async (a sync passthrough returns the promise "
        "uncaught, so agent() throws bypass the degradation catch)"
    )
    body = fn_m.group(0)
    assert "catch" in body and "return null" in body, (
        "dispatch() must catch agent() throws and return null so failures "
        "flow into the loop's existing degradation paths (Sylveste-kp9)"
    )
