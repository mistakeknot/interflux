"""Structural checks for the mechanical concurrency cap (issue #5).

The MAX_CONCURRENT_AGENTS cap was previously prose the orchestrating LLM was
asked to honor. These tests pin the moving parts that make it mechanically
enforced: the budget key the resolution order depends on, the enforcement
script, and the docs that reference it.
"""

import yaml

import pytest


@pytest.fixture(scope="session")
def budget(project_root):
    path = project_root / "config" / "flux-drive" / "budget.yaml"
    return yaml.safe_load(path.read_text())


def test_budget_has_dispatch_section(budget):
    """launch.md's resolution order references budget.yaml dispatch.max_concurrent_agents.

    Without this key that tier was a dead path (see issue #5).
    """
    assert "dispatch" in budget, "budget.yaml is missing the `dispatch:` section"
    assert "max_concurrent_agents" in budget["dispatch"]


def test_max_concurrent_agents_is_positive_int(budget):
    val = budget["dispatch"]["max_concurrent_agents"]
    assert isinstance(val, int) and val > 0, (
        f"dispatch.max_concurrent_agents must be a positive int, got {val!r}"
    )


def test_dispatch_script_exists_and_executable(scripts_dir):
    script = scripts_dir / "flux-dispatch.sh"
    assert script.exists(), "scripts/flux-dispatch.sh (concurrency enforcement) is missing"
    import os

    assert os.access(script, os.X_OK), "flux-dispatch.sh must be executable"


def test_dispatch_script_implements_core_subcommands(scripts_dir):
    text = (scripts_dir / "flux-dispatch.sh").read_text()
    for sub in ("acquire", "release", "count", "wait", "reset"):
        assert f"{sub})" in text, f"flux-dispatch.sh missing `{sub}` subcommand"
    # Must be a real flock-guarded semaphore, not prose.
    assert "flock" in text, "flux-dispatch.sh must use flock for admission control"


def test_launch_doc_references_enforcement_script(project_root):
    launch = (project_root / "skills" / "flux-engine" / "phases" / "launch.md").read_text()
    assert "flux-dispatch.sh" in launch, (
        "launch.md must reference the enforcement script, not describe the cap as prose only"
    )
    # The cap should be described as enforced, not merely a loop the LLM follows.
    assert "mechanically enforced" in launch.lower() or "admission control" in launch.lower()


def test_fd_allocation_table_registers_dispatch_lock(scripts_dir):
    readme = (scripts_dir / "README.md").read_text()
    assert "flux-dispatch.sh" in readme, "scripts/README.md fd table must register the dispatch lock"
    assert "204" in readme, "dispatch lock should use fd 204 per README convention"
