import json
import subprocess
import sys
import pytest
import yaml
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "select-review-route.py"
DEFAULTS = ROOT / "config" / "flux-melange" / "defaults.yaml"


def resolve(purpose: str, producer: str | None = None) -> dict:
    command = [sys.executable, str(SCRIPT), "--purpose", purpose]
    if producer:
        command += ["--producer", producer]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def peer_codex() -> dict:
    return yaml.safe_load(DEFAULTS.read_text())["peers"]["runtimes"]["codex"]


# --- Bulk mirrors: one source of truth --------------------------------------
#
# Bulk mirrors and consequential validation are different jobs that briefly
# shared a table. A mirror has no producer to be separated from, so its model is
# whatever `peers.runtimes` says; only validation needs the producer-relative
# chain. When `routes.bulk` still pointed at `sol-bulk`, this selector and
# `peers.runtimes.codex` answered the same question differently and nothing in
# the run output revealed which rule an orchestrator had applied.


def test_bulk_mirror_resolves_from_the_peer_table():
    candidate = resolve("bulk")["candidates"][0]
    assert candidate["profile"] == "peers.runtimes.codex"
    assert candidate["model"] == peer_codex()["model"] == "gpt-6-astra"
    assert candidate["reasoning_effort"] == "medium"
    assert candidate["service_tier"] == "fast"


def test_bulk_mirror_cannot_disagree_with_the_peer_table():
    """The split this test exists to prevent: two tables, one answer."""
    candidate = resolve("bulk")["candidates"][0]
    configured = peer_codex()
    assert candidate["model"] == configured["model"]
    assert candidate["invoke"] == configured["invoke"]
    assert f'model_reasoning_effort="{candidate["reasoning_effort"]}"' in candidate["invoke"]
    assert f'service_tier="{candidate["service_tier"]}"' in candidate["invoke"]


def test_bulk_mirror_needs_no_producer_identity():
    payload = resolve("bulk")
    assert payload["producer_identity"] is None
    assert payload["validator_relationship"] is None
    assert payload["excluded"] == []


def test_sol_remains_the_terminal_validation_fallback():
    """Guards the tempting wrong fix: editing sol-bulk's model in place.

    `sol-bulk` ends all three validation chains, including the Astra-producer
    chain that must never resolve back to Astra. Retargeting it to satisfy the
    mirror ruling would have silently changed reviewer separation.
    """
    for producer in ("claude/fable", "kimi/k3", "codex/gpt-6-astra"):
        chain = [item["model"] for item in resolve("validation", producer)["candidates"]]
        assert chain[-1] == "gpt-5.6-sol", producer


def test_claude_producer_selects_astra_high_standard():
    candidate = resolve("validation", "claude/fable")["candidates"][0]
    assert candidate["model"] == "gpt-6-astra"
    assert candidate["reasoning_effort"] == "high"
    assert candidate["service_tier"] == "standard"
    assert candidate["minimum_codex_version"] == "0.153.1"
    assert 'service_tier="default"' in candidate["invoke"]


def test_kimi_producer_selects_astra():
    assert resolve("validation", "kimi/k3")["candidates"][0]["model"] == "gpt-6-astra"


def test_astra_producer_excludes_astra_and_prefers_external_fable():
    candidates = resolve("validation", "codex/gpt-6-astra")["candidates"]
    assert candidates[0]["kind"] == "claude"
    assert candidates[0]["model"] == "claude-fable-5-1"
    assert all(item["model"] != "gpt-6-astra" for item in candidates)
    assert [item["model"] for item in candidates] == ["claude-fable-5-1", "k3", "gpt-5.6-sol"]
    assert 'NTSMR_KIMI_MODEL="{model}" KIMI_CLI_MODEL="kimi-code/{model}"' in candidates[1]["invoke"]


def test_validation_requires_producer_identity():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--purpose", "validation"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--producer" in result.stderr


@pytest.mark.parametrize("producer", [
    "anthropic/claude-fable-5-1[1m]", "claude-code/claude-fable-5-1-20260901",
    "openai/gpt-6-astra-2026-09-01", "codex/gpt-5.6-20260901",
    "moonshot/kimi-code/k3",
])
def test_reviewers_exclude_canonical_producer(producer):
    payload = resolve("validation", producer)
    identity = payload["producer_identity"]["model_identity"]
    assert all(item["model_identity"] != identity for item in payload["candidates"])
    assert payload["validator_relationship"] == "different-model"
    if identity == "claude-fable-5-1":
        assert payload["candidates"][0]["model"] == "gpt-6-astra"


def test_unknown_producer_alias_fails_closed():
    result = subprocess.run([sys.executable, str(SCRIPT), "--purpose", "validation", "--producer", "codex/custom-alias"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2
    assert "identity" in result.stderr
