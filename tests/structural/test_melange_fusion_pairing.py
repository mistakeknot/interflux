"""Pin the fusion candidate gate in melange-workflow.js against a real run.

FUSE is the mechanic flux-melange is named for (references/fusion.md), and it
was dead. The controller's SHARED_HEAT term compared two findings' whole
normalized `location` strings for equality — but a probe writes `location` as
free-form prose naming several files and anchors at once, so two lenses that
both fired on decision 9 of the same document produced different strings and
scored 0. Across the `orthophoto-pass-and-address-gauge` run (10 lenses, 3
rounds, 33 findings) SHARED_HEAT was 0 for all 45 candidate pairs in every
round, the hard gate never opened, `pairs` was always empty, and not one FUSE
directive was ever issued.

The fix makes region membership a SET (`locationKeys`) as fusion.md specifies —
"the same file / section / line-range". This test executes the shipped block
against that run's real locations and asserts both directions: the old method
still scores 0 here (so the regression is witnessed, not just described), and
the shipped method admits pairs at the default gate.

The pairing block is sliced out of the JS between marker comments and run under
node. Node is not a CI dependency for this repo, so the test skips when it is
absent rather than failing.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_JS = (
    ROOT / "skills" / "flux-melange-engine" / "workflow" / "melange-workflow.js"
)
FIXTURE = ROOT / "tests" / "fixtures" / "melange" / "fusion-pairing"
LEDGER = FIXTURE / "heat-ledger.jsonl"
TARGET = "docs/brainstorms/2026-09-13-orthophoto-and-address-gauge-brainstorm.md"

BEGIN = "// ---- BEGIN testable: location regions"
END = "// ---- END testable: location regions"

# references/workflow-args.md § Args contract — fusion.sharedHeatGate default.
SHARED_HEAT_GATE = 2


def _slice_block(src: str) -> str:
    start = src.index(BEGIN)
    end = src.index(END)
    assert start < end, "location-region markers are out of order"
    return src[start:end]


@pytest.fixture(scope="module")
def workflow_src() -> str:
    return WORKFLOW_JS.read_text()


@pytest.fixture(scope="module")
def findings() -> list[dict]:
    return [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip()]


def _run_node(script: str) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover - environment dependent
        pytest.skip("node not available — pairing block cannot be executed")
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _harness(block: str, findings: list[dict]) -> str:
    """Block + the old string-equality method + a pairwise sweep over the run."""
    return f"""
const normKey = (loc) =>
  String(loc || "").toLowerCase().replace(/^brainstorm\\s+/, "")
    .replace(/:\\d+(-\\d+)?$/, "").trim();

{block}

// The pre-fix SHARED_HEAT: exact equality between whole normalized locations.
function legacySharedHeat(fa, fb) {{
  const keysA = new Set(fa.map((f) => normKey(f.location)));
  return [...new Set(fb.map((f) => normKey(f.location)))].filter((k) => keysA.has(k)).length;
}}

const FINDINGS = {json.dumps(findings)};
const TARGET = {json.dumps(TARGET)};

const byLens = {{}};
for (const f of FINDINGS)
  for (const a of f.agents) (byLens[a] = byLens[a] || []).push(f);
const lenses = Object.keys(byLens).sort();

const rows = [];
for (let i = 0; i < lenses.length; i++)
  for (let j = i + 1; j < lenses.length; j++) {{
    const [a, b] = [lenses[i], lenses[j]];
    rows.push({{
      pair: [a, b],
      legacy: legacySharedHeat(byLens[a], byLens[b]),
      shared: sharedRegionCount(byLens[a], byLens[b], TARGET),
    }});
  }}
rows.sort((x, y) => y.shared - x.shared);
console.log(JSON.stringify({{
  lenses: lenses.length,
  pairs: rows.length,
  rows,
  sampleKeys: [...locationKeys(FINDINGS[1].location, TARGET)],
  targetOnlyKeys: [...locationKeys(TARGET + " line 47 (decision 9)", TARGET)],
}}));
"""


@pytest.fixture(scope="module")
def sweep(workflow_src, findings) -> dict:
    return _run_node(_harness(_slice_block(workflow_src), findings))


def test_block_markers_present(workflow_src):
    assert BEGIN in workflow_src and END in workflow_src, (
        "the location-region block lost its markers — this test slices the "
        "shipped code between them, it does not reimplement it"
    )


def test_legacy_string_equality_scored_zero_on_a_real_run(sweep):
    """Witness the defect: whole-location equality never matched, so FUSE died."""
    assert sweep["pairs"] == 45 and sweep["lenses"] == 10, sweep
    worst = max(r["legacy"] for r in sweep["rows"])
    assert worst == 0, (
        "fixture no longer reproduces the zero-FUSE run — the regression this "
        f"test guards is not being exercised (best legacy shared_heat {worst})"
    )


def test_region_sets_admit_fusion_candidates(sweep):
    eligible = [r for r in sweep["rows"] if r["shared"] >= SHARED_HEAT_GATE]
    assert eligible, (
        "no lens pair clears the default sharedHeatGate="
        f"{SHARED_HEAT_GATE} on a 10-lens / 33-finding run — FUSE is dead again"
    )
    # Not a flood either: fusion is a top-K pick, not every pair.
    assert len(eligible) < sweep["pairs"], "every pair eligible — gate is inert"
    best = sweep["rows"][0]
    assert best["shared"] >= 3, f"best pair too weak: {best}"


def test_line_anchors_are_scoped_to_their_file(sweep):
    """`lib.rs:36` and `brainstorm.md line 36` are different regions."""
    keys = sweep["sampleKeys"]
    assert any(k.startswith("f:crates/city-build/src/lib.rs") for k in keys), keys
    assert "crates/city-build/src/lib.rs#l36" in keys, keys
    assert not any(k == "#l36" or k == "l:36" for k in keys), keys


def test_target_file_is_not_itself_a_shared_region(sweep):
    """Every lens reviews the target; crediting it would gift every pair a point."""
    keys = sweep["targetOnlyKeys"]
    assert f"f:{TARGET}" not in keys, keys
    assert f"{TARGET}#l47" in keys and f"{TARGET}#d9" in keys, keys
