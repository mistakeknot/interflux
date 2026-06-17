"""Structural + behavioral checks for transient-failure backpressure (issue #9).

Finding C-2: launch.md cited ~30% retry-token waste at 16-agent fan-out, yet
dispatch had no 429/backoff handling. These tests pin the parts that make the
backpressure path real: the enforcement script, its subcommands, the budget
config it reads, the docs that describe the enforced path, and a few end-to-end
behaviors (classification, decrease-floors-the-cap, and that flux-dispatch.sh
acquire honors the decreased cap).
"""

import os
import subprocess
import tempfile

import pytest
import yaml


@pytest.fixture(scope="session")
def budget(project_root):
    path = project_root / "config" / "flux-drive" / "budget.yaml"
    return yaml.safe_load(path.read_text())


@pytest.fixture()
def output_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _run(script, *args, env=None, input_text=None):
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env=full_env,
        input=input_text,
    )


# --- script + subcommands exist ------------------------------------------

def test_backoff_script_exists_and_executable(scripts_dir):
    script = scripts_dir / "flux-backoff.sh"
    assert script.exists(), "scripts/flux-backoff.sh (issue #9 backpressure) is missing"
    assert os.access(script, os.X_OK), "flux-backoff.sh must be executable"


def test_backoff_script_implements_subcommands(scripts_dir):
    text = (scripts_dir / "flux-backoff.sh").read_text()
    for sub in ("classify", "delay", "sleep", "decrease", "increase", "effective", "reset"):
        assert f"{sub})" in text, f"flux-backoff.sh missing `{sub}` subcommand"


def test_backoff_shares_dispatch_fd_204(scripts_dir):
    """The congestion cap must be mutated under the SAME lock as the slot count
    so decreases serialize with acquires (README fd-allocation rule)."""
    text = (scripts_dir / "flux-backoff.sh").read_text()
    assert "204" in text and ".dispatch-slots.lock" in text, (
        "flux-backoff.sh must mutate the cap under the fd-204 dispatch-slots lock"
    )


# --- dispatch script wired to the congestion cap -------------------------

def test_dispatch_reads_effective_cap(scripts_dir):
    text = (scripts_dir / "flux-dispatch.sh").read_text()
    assert "effective_max" in text, "flux-dispatch.sh acquire must compute an effective cap"
    assert ".dispatch-cap" in text, "flux-dispatch.sh must read the congestion cap file"
    assert "maxcap)" in text, "flux-dispatch.sh must expose maxcap for backoff seeding"


# --- budget config ---------------------------------------------------------

def test_budget_has_backoff_section(budget):
    assert "dispatch" in budget
    assert "backoff" in budget["dispatch"], "budget.yaml dispatch.backoff section missing"


def test_backoff_config_values_are_positive(budget):
    cfg = budget["dispatch"]["backoff"]
    for key in ("base_delay_secs", "max_delay_secs", "factor",
                "decrease_factor", "min_effective_cap"):
        assert key in cfg, f"dispatch.backoff.{key} missing"
        assert isinstance(cfg[key], int) and cfg[key] > 0, f"{key} must be a positive int"
    assert cfg["decrease_factor"] >= 2, "decrease_factor must be >= 2 to actually decrease"
    assert cfg["max_delay_secs"] >= cfg["base_delay_secs"]


# --- docs describe the ENFORCED path -------------------------------------

def test_launch_doc_documents_backpressure(project_root):
    launch = (project_root / "skills" / "flux-engine" / "phases" / "launch.md").read_text().lower()
    assert "flux-backoff.sh" in launch, "launch.md must reference the backpressure script"
    assert "backpressure" in launch
    assert "429" in launch or "rate-limit" in launch or "rate limit" in launch
    # The distinguishing properties of the fix:
    assert "jitter" in launch, "launch.md must document exponential backoff + jitter"
    assert "decrease" in launch, "launch.md must document multiplicative concurrency decrease"


def test_shared_contracts_documents_transient_class(project_root):
    sc = (project_root / "skills" / "flux-engine" / "phases" / "shared-contracts.md").read_text()
    low = sc.lower()
    assert "transient" in low, "shared-contracts.md must name the transient failure class"
    assert "flux-backoff.sh" in sc
    # Must distinguish transient from the existing same-concurrency retry-race path.
    assert "before the 300s timeout" in low or "before the 300s" in low


def test_readme_registers_backoff_on_fd_204(scripts_dir):
    readme = (scripts_dir / "README.md").read_text()
    assert "flux-backoff.sh" in readme, "scripts/README.md must mention flux-backoff.sh"


# --- behavioral: classification ------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("API Error 429 Too Many Requests", "transient"),
        ("rate_limit_error", "transient"),
        ("overloaded_error", "transient"),
        ("HTTP 503 Service Unavailable", "transient"),
        ("HTTP 529 overloaded", "transient"),
        (
            "API Error: Claude Code is unable to respond to this request, "
            "which appears to violate our Usage Policy",
            "terminal",
        ),
        ("segmentation fault (core dumped)", "unknown"),
        ("completed at 4290 tokens", "unknown"),  # a year-like number is not 429
    ],
)
def test_classify_behavior(scripts_dir, text, expected):
    r = _run(scripts_dir / "flux-backoff.sh", "classify", input_text=text)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == expected, f"{text!r} -> {r.stdout.strip()!r} (want {expected})"


# --- behavioral: backoff bounds ------------------------------------------

def test_delay_within_window_bounds(scripts_dir):
    env = {"FLUX_BACKOFF_BASE_DELAY": "2", "FLUX_BACKOFF_FACTOR": "2", "FLUX_BACKOFF_MAX_DELAY": "10"}
    # attempt 1 window = 2; attempt 6 raw = 64 capped at 10.
    for _ in range(30):
        d1 = int(_run(scripts_dir / "flux-backoff.sh", "delay", "1", env=env).stdout.strip())
        assert 0 <= d1 <= 2
        d6 = int(_run(scripts_dir / "flux-backoff.sh", "delay", "6", env=env).stdout.strip())
        assert 0 <= d6 <= 10


def test_delay_has_jitter(scripts_dir):
    env = {"FLUX_BACKOFF_BASE_DELAY": "8", "FLUX_BACKOFF_MAX_DELAY": "60"}
    vals = {
        _run(scripts_dir / "flux-backoff.sh", "delay", "4", env=env).stdout.strip()
        for _ in range(25)
    }
    assert len(vals) >= 2, "full jitter must produce varying delays"


# --- behavioral: multiplicative decrease + composition -------------------

def test_decrease_halves_and_floors(scripts_dir, output_dir):
    dispatch = scripts_dir / "flux-dispatch.sh"
    backoff = scripts_dir / "flux-backoff.sh"
    _run(dispatch, "reset", output_dir, "6")
    seq = [_run(backoff, "decrease", output_dir, "6").stdout.strip() for _ in range(4)]
    assert seq == ["3", "2", "1", "1"], seq  # 6/2=3, 3->2, 2->1, floored at 1


def test_acquire_honors_decreased_cap(scripts_dir, output_dir):
    """The end-to-end guarantee: a 429-driven decrease throttles real acquires."""
    dispatch = scripts_dir / "flux-dispatch.sh"
    backoff = scripts_dir / "flux-backoff.sh"
    _run(dispatch, "reset", output_dir, "6")
    _run(backoff, "decrease", output_dir, "6")  # 6 -> 3
    _run(backoff, "decrease", output_dir, "6")  # 3 -> 2 effective
    # Two acquires succeed against the throttled cap of 2 ...
    assert _run(dispatch, "acquire", output_dir, "6", "2").returncode == 0
    assert _run(dispatch, "acquire", output_dir, "6", "2").returncode == 0
    # ... the third must block/time out even though BASE max is 6.
    assert _run(dispatch, "acquire", output_dir, "6", "1").returncode == 1
    count = _run(dispatch, "count", output_dir).stdout.strip()
    assert count == "2", count


def test_reset_clears_congestion_cap(scripts_dir, output_dir):
    dispatch = scripts_dir / "flux-dispatch.sh"
    backoff = scripts_dir / "flux-backoff.sh"
    _run(dispatch, "reset", output_dir, "6")
    _run(backoff, "decrease", output_dir, "6")
    assert os.path.exists(os.path.join(output_dir, ".dispatch-cap"))
    _run(dispatch, "reset", output_dir, "6")
    assert not os.path.exists(os.path.join(output_dir, ".dispatch-cap"))
