"""Pin flux-melange's adaptive peer-model resolution.

`--peers` mirrors run on whatever `scripts/detect-runtimes.sh` says this
environment can reach, so a wrong answer here does not fail loudly — it
silently mirrors on a model nobody chose, and the Parley phase reconciles
syntheses whose provenance is a lie. The two fallbacks that matter:

  codex  — gpt-6-astra requires Codex CLI >= 0.153.1 (the routing policy's
           minimum_codex_version for the Astra profile). An older CLI must
           degrade to gpt-5.6-sol rather than failing at invoke time.
  hermes — deepseek/deepseek-v4.1-flash exists only on providers the user has
           actually configured. With no provider cache, hermes must fall back
           to its own CLI default (model null), never to a guess.

The ladder is duplicated by design between the script and
config/flux-melange/defaults.yaml (the same arrangement kimi uses for its two
lanes, so probe and invoke cannot disagree). These tests exist to make that
duplication break loudly when only one side is edited.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DETECT = PROJECT_ROOT / "scripts" / "detect-runtimes.sh"
DEFAULTS = PROJECT_ROOT / "config" / "flux-melange" / "defaults.yaml"

ASTRA_MIN_CODEX = "0.153.1"


def _version_at_least(a: str, b: str) -> bool:
    """Call the script's own comparator rather than reimplementing it."""
    script = textwrap.dedent(
        f"""
        source <(sed -n '/^version_at_least/,/^}}/p' "{DETECT}")
        version_at_least "{a}" "{b}"
        """
    )
    return subprocess.run(["bash", "-c", script]).returncode == 0


@pytest.mark.parametrize(
    "have,want,expected",
    [
        ("0.154.0", ASTRA_MIN_CODEX, True),
        ("0.153.1", ASTRA_MIN_CODEX, True),  # boundary: equal satisfies
        ("0.153.0", ASTRA_MIN_CODEX, False),
        ("0.152.9", ASTRA_MIN_CODEX, False),
        # 0.99 > 0.153 lexically but is older by version order — the case a
        # naive string compare gets wrong, and the reason sort -V is used.
        ("0.99.0", ASTRA_MIN_CODEX, False),
        ("1.0.0", ASTRA_MIN_CODEX, True),
    ],
)
def test_codex_version_gate_orders_by_version_not_string(have, want, expected):
    assert _version_at_least(have, want) is expected


def test_detect_emits_valid_json_with_the_adaptive_contract():
    """Charter parses this output; every runtime must carry the full contract."""
    proc = subprocess.run(
        ["bash", str(DETECT)], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, "absence is data, not an error — exit must stay 0"
    data = json.loads(proc.stdout)

    for runtime in ("codex", "hermes", "kimi"):
        entry = data[runtime]
        assert "available" in entry
        # Resolved model and its justification travel together, so a downgrade
        # is always explainable in the plan display.
        assert "model" in entry, f"{runtime} must report a resolved model"
        assert "model_reason" in entry, f"{runtime} must say why"
        # Consent depends on this flag; charter cannot infer it.
        assert isinstance(entry["sandboxed"], bool), f"{runtime} must declare sandboxing"


def test_hermes_falls_back_to_cli_default_without_a_provider_cache():
    """No configured provider carrying the model => null, not a guess."""
    if shutil.which("hermes") is None:
        pytest.skip("hermes not installed; resolver short-circuits before the cache read")
    script = textwrap.dedent(
        f"""
        export HOME=/tmp/interflux-no-such-home-$$
        source <(sed -n '/^resolve_hermes/,/^}}/p' "{DETECT}")
        resolve_hermes
        """
    )
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=60
    ).stdout
    assert '"model":null' in out, f"expected a null model, got: {out}"
    assert "deepseek" not in out.split("model_reason")[0], "must not assert an unreachable model"


def test_config_and_script_agree_on_the_preferred_models():
    """The duplication is deliberate; this makes a one-sided edit fail."""
    cfg = yaml.safe_load(DEFAULTS.read_text())
    runtimes = cfg["peers"]["runtimes"]
    script = DETECT.read_text()

    assert runtimes["codex"]["model"] == "gpt-6-astra"
    assert "gpt-6-astra" in script and "gpt-5.6-sol" in script, "codex ladder drifted"
    assert ASTRA_MIN_CODEX in script, "Astra's minimum Codex version drifted"

    # hermes pins its provider-prefixed id in the invoke template, because the
    # '/' fails the peer-model regex — so model: stays null on purpose.
    assert runtimes["hermes"]["model"] is None
    assert "deepseek/deepseek-v4.1-flash" in runtimes["hermes"]["invoke"]
    assert "--provider openrouter" in runtimes["hermes"]["invoke"]
    assert "deepseek/deepseek-v4.1-flash" in script, "hermes ladder drifted"

    assert runtimes["kimi"]["model"] == "k3"


def test_consent_gate_is_declared():
    cfg = yaml.safe_load(DEFAULTS.read_text())
    consent = cfg["peers"]["consent"]
    # Default true keeps the three configured mirrors; the knob must exist so a
    # user can refuse unsandboxed agents on a sensitive target.
    assert consent["auto_includes_unsandboxed"] is True


MELANGE_SKILL = PROJECT_ROOT / "skills" / "flux-melange-engine"
CHARTER = MELANGE_SKILL / "phases" / "charter.md"
PEER_DOCS = [CHARTER, MELANGE_SKILL / "references" / "peer-runtimes.md"]


@pytest.mark.parametrize("doc", PEER_DOCS, ids=lambda p: p.name)
def test_peer_docs_do_not_pin_bulk_mirrors_to_a_stale_model(doc):
    """The defect was prose, not code: the docs claimed a model config denied.

    An orchestrator reads these top to bottom. While one paragraph said bulk
    mirrors "retain the configured GPT-5.6 Sol/high/Fast profile" and a later
    step said to resolve the model from `peers.runtimes`, both readings were
    defensible and the plan display printed only the resolved model — so the
    substitution was invisible in the run output.
    """
    text = doc.read_text()
    # Scoped to sentences about mirrors: naming GPT-5.6 Sol is still correct when
    # describing the validation chain, where it is the terminal fallback.
    # \bsol\b, not "sol" — that substring also lives inside "resolve".
    names_a_model = re.compile(r"gpt-|\bsol\b", re.IGNORECASE)
    for sentence in re.split(r"(?<=[.:])\s", text):
        if "bulk mirror" not in sentence.lower():
            continue
        assert not names_a_model.search(sentence), (
            f"{doc.name} pins a mirror model instead of deferring to config: {sentence.strip()!r}"
        )


def test_charter_names_the_authoritative_peer_table():
    assert "peers.runtimes" in CHARTER.read_text()


def test_charter_warns_that_every_unsandboxed_lane_is_unsandboxed():
    """kimi's CLI lane auto-approves tool use in the project root, like hermes.

    The trust warning is the only place a user sees this before the run starts,
    so an omission here reads as an assurance.
    """
    charter = CHARTER.read_text()
    warning = charter[charter.index("trust warning"):]
    warning = warning[: warning.index("\n\n")]
    for runtime in ("hermes", "kimi"):
        assert runtime in warning, f"{runtime} missing from the peer trust warning"
