"""A peer mirror that died must not be reportable as a mirror that found nothing.

Sylveste-cg1. The shim contract tells a shim, on CLI failure or timeout, to
return "a minimally valid object for the schema (empty arrays; any required
string field = SHIM-FAILURE: <reason>)". Eight of the ten top-level schemas
have no required string field, so on those the degraded object is just
`{"findings": []}` — byte-identical to a probe that ran fine and found nothing.

That is not merely a reporting gap. In `runProbes`, a null result is filtered
out and counted in `failed`; a truthy `{findings: []}` survives as a SUCCESS
contributing zero findings. `scoreRound` then sees roundYield 0, which is
`<= diminishingThreshold`, and halts the loop DRY — so a mirror that never ran
can report a convergence it never earned, and Parley reconciles its synthesis
as an independent opinion.

The fix routes every shim failure to null, which is the value the loop already
handles correctly. These tests execute the two pure helpers under node rather
than grepping for them, so a helper that exists but does not work still fails.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_JS = (
    PROJECT_ROOT / "skills" / "flux-melange-engine" / "workflow" / "melange-workflow.js"
)
DEFAULTS = PROJECT_ROOT / "config" / "flux-melange" / "defaults.yaml"

SOURCE = WORKFLOW_JS.read_text()


def extract(name: str) -> str:
    """Pull one top-level `function name(...) {...}` out by brace matching."""
    start = SOURCE.index(f"function {name}(")
    depth, i = 0, SOURCE.index("{", start)
    for j in range(i, len(SOURCE)):
        if SOURCE[j] == "{":
            depth += 1
        elif SOURCE[j] == "}":
            depth -= 1
            if depth == 0:
                return SOURCE[start : j + 1]
    raise AssertionError(f"unbalanced braces extracting {name}")


def run_node(*, helpers: list[str], body: str):
    script = "\n".join(extract(h) for h in helpers) + "\n" + body
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# --- the marker must be carriable on every schema ---------------------------


def test_mirror_schema_adds_a_required_status_to_any_schema():
    out = run_node(
        helpers=["mirrorSchema"],
        body="""
const cases = {
  arrayOnly:  { type: "object", required: ["findings"], properties: { findings: { type: "array" } } },
  boolOnly:   { type: "object", required: ["written"],  properties: { written: { type: "boolean" } } },
  noRequired: { type: "object", properties: { x: { type: "string" } } },
};
const out = {};
for (const [k, v] of Object.entries(cases)) {
  const m = mirrorSchema(v);
  out[k] = {
    required: m.required,
    statusType: m.properties.shim_status.type,
    baseUntouched: v.required ? v.required.includes("shim_status") : false,
    keptOriginals: (v.required || []).every((r) => m.required.includes(r)),
  };
}
console.log(JSON.stringify(out));
""",
    )
    for name, got in out.items():
        assert "shim_status" in got["required"], name
        assert got["statusType"] == "string", name
        assert got["keptOriginals"], name
        assert not got["baseUntouched"], f"{name}: mirrorSchema mutated the base schema"


# --- a failure must become null, not an empty success -----------------------


@pytest.mark.parametrize(
    "payload,expect_failure",
    [
        ({"shim_status": "SHIM-FAILURE: hermes CLI timed out after 600s"}, True),
        ({"shim_status": "shim-failure: lowercase still counts"}, True),
        ({"findings": [], "shim_status": "ok"}, False),
        ({"findings": [{"claim": "x"}], "shim_status": "ok"}, False),
        # A shim that forgot the field is treated as failed: an unverifiable
        # mirror result is exactly what this bug was.
        ({"findings": []}, True),
        (None, True),
    ],
)
def test_shim_failure_reason_detects_every_degraded_shape(payload, expect_failure):
    out = run_node(
        helpers=["shimFailureReason"],
        body=f"console.log(JSON.stringify({{r: shimFailureReason({json.dumps(payload)})}}));",
    )
    assert bool(out["r"]) is expect_failure, out


def test_empty_findings_with_ok_status_is_a_real_result():
    """The honest case must survive — otherwise the fix eats true negatives."""
    out = run_node(
        helpers=["shimFailureReason"],
        body='console.log(JSON.stringify({r: shimFailureReason({findings: [], shim_status: "ok"})}));',
    )
    assert out["r"] in (None, "", False)


# --- timeouts are per-runtime, and never retried ----------------------------


def test_shim_timeout_is_per_runtime_not_a_hardcoded_constant():
    assert "timeout: 600000" not in SOURCE, (
        "one flat timeout cannot serve a fast mirror and a 7.7x-slower one"
    )
    assert "timeoutMs" in SOURCE, "shim must take a per-runtime timeout"


def test_a_timeout_is_not_retried():
    """Re-running a timed-out CLI doubles the waste and cannot help."""
    shim = SOURCE[SOURCE.index("function shimWrap("):]
    shim = shim[: shim.index("\nfunction ", 1)] if "\nfunction " in shim[1:] else shim
    retry = re.search(r"re-run ONCE[^\n]*", shim)
    assert retry, "shim lost its retry instruction entirely"
    assert "timed out" in retry.group(0) or "timeout" in retry.group(0).lower(), (
        f"retry instruction does not exempt timeouts: {retry.group(0)!r}"
    )


def test_a_failing_mirror_cannot_take_down_the_run():
    """Routing failures to null makes dead mirrors hit real hard floors.

    Before the fix a dead mirror returned fake successes and never threw; now
    it can trip `both seed probes failed`. That must stay isolated: mirror
    throws are caught into R.failed and become report caveats, and only the
    PRIMARY loop's failure is allowed to end the run.
    """
    assert "runMelange(R).catch(" in SOURCE, "mirror loops must be individually caught"
    assert re.search(r"if \(primary\.failed\)\s*\n?\s*throw new Error", SOURCE), (
        "only the primary's failure may throw"
    )
    assert "mirrorCaveats" in SOURCE, "a failed mirror must surface as a caveat"


def test_every_peer_runtime_declares_a_timeout():
    import yaml

    runtimes = yaml.safe_load(DEFAULTS.read_text())["peers"]["runtimes"]
    for kind, rt in runtimes.items():
        assert isinstance(rt.get("timeout_ms"), int), f"{kind} has no timeout_ms"
        assert rt["timeout_ms"] >= 60_000, f"{kind} timeout is implausibly short"
    # K3 is documented in this same file as ~7.7x slower than gpt-5.6-luna;
    # giving it the same window as codex is what produced silent empty probes.
    assert runtimes["kimi"]["timeout_ms"] > runtimes["codex"]["timeout_ms"]
