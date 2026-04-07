"""Tests for flux-drive content slicing (consolidated in phases/slicing.md)."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def slicing_path(project_root: Path) -> Path:
    return project_root / "skills" / "flux-drive" / "phases" / "slicing.md"


@pytest.fixture(scope="session")
def slicing_content(project_root: Path) -> str:
    return (project_root / "skills" / "flux-drive" / "phases" / "slicing.md").read_text()


@pytest.fixture(scope="session")
def flux_drive_skill(project_root: Path) -> str:
    return (project_root / "skills" / "flux-drive" / "SKILL.md").read_text()


@pytest.fixture(scope="session")
def launch_phase(project_root: Path) -> str:
    return (project_root / "skills" / "flux-drive" / "phases" / "launch.md").read_text()


@pytest.fixture(scope="session")
def shared_contracts(project_root: Path) -> str:
    return (project_root / "skills" / "flux-drive" / "phases" / "shared-contracts.md").read_text()


@pytest.fixture(scope="session")
def synthesize_phase(project_root: Path) -> str:
    return (project_root / "skills" / "flux-drive" / "phases" / "synthesize.md").read_text()


# --- slicing.md existence and structure ---


def test_slicing_file_exists(slicing_path: Path):
    """phases/slicing.md exists."""
    assert slicing_path.exists(), "skills/flux-drive/phases/slicing.md is missing"


def test_slicing_has_both_modes(slicing_content: str):
    """slicing.md covers both diff slicing and document slicing."""
    assert "## Diff Slicing" in slicing_content
    assert "## Document Slicing" in slicing_content


# --- Routing patterns ---


def test_slicing_covers_all_agents(slicing_content: str):
    """slicing.md mentions all 7 fd-* agents."""
    agents = [
        "fd-architecture",
        "fd-safety",
        "fd-correctness",
        "fd-performance",
        "fd-user-product",
        "fd-quality",
        "fd-game-design",
    ]
    for agent in agents:
        assert agent in slicing_content, (
            f"slicing.md does not mention {agent}"
        )


def test_slicing_has_cross_cutting_section(slicing_content: str):
    """slicing.md defines cross-cutting agents."""
    assert "Cross-Cutting Agents" in slicing_content


def test_slicing_has_domain_specific_sections(slicing_content: str):
    """slicing.md has sections for domain-specific agents."""
    assert "Domain-Specific Agents" in slicing_content
    for agent in ["fd-safety", "fd-correctness", "fd-performance", "fd-user-product", "fd-game-design"]:
        assert f"#### {agent}" in slicing_content, (
            f"slicing.md missing section for {agent}"
        )


def test_slicing_has_priority_patterns(slicing_content: str):
    """Each domain agent section has priority file patterns and keywords."""
    assert "Priority file patterns" in slicing_content
    assert "Priority hunk keywords" in slicing_content


# --- Synthesis contracts ---


def test_slicing_has_synthesis_contracts(slicing_content: str):
    """slicing.md contains synthesis contracts."""
    assert "## Synthesis Contracts" in slicing_content
    assert "Convergence adjustment" in slicing_content


def test_slicing_has_synthesis_rules(slicing_content: str):
    """slicing.md documents synthesis rules for slicing."""
    assert "Convergence adjustment" in slicing_content
    assert "discovered beyond sliced scope" in slicing_content
    assert "No silence penalty" in slicing_content


# --- Report template ---


def test_slicing_has_report_template(slicing_content: str):
    """slicing.md has a slicing report template."""
    assert "Slicing report" in slicing_content
    assert "Routing improvements" in slicing_content


# --- Thresholds and overrides ---


def test_slicing_has_thresholds(slicing_content: str):
    """slicing.md defines 80% threshold and safety override."""
    assert "80%" in slicing_content
    assert "Safety override" in slicing_content


# --- SKILL.md references ---


def test_skill_mentions_input_type_diff(flux_drive_skill: str):
    """SKILL.md defines INPUT_TYPE = diff."""
    assert "INPUT_TYPE = diff" in flux_drive_skill


def test_skill_has_diff_profile(flux_drive_skill: str):
    """SKILL.md contains a Diff Profile section."""
    assert "Diff Profile" in flux_drive_skill
    assert "slicing_eligible" in flux_drive_skill


def test_skill_detects_diff_content(flux_drive_skill: str):
    """SKILL.md detects diff inputs by content signature."""
    assert "diff --git" in flux_drive_skill
    assert "--- a/" in flux_drive_skill


def test_skill_references_slicing(flux_drive_skill: str):
    """SKILL.md references slicing.md for content routing."""
    assert "slicing.md" in flux_drive_skill


# --- Phase file references ---


def test_launch_references_slicing(launch_phase: str):
    """launch.md references slicing.md for sliced content."""
    assert "slicing.md" in launch_phase
    assert "Step 2.1b" in launch_phase


def test_launch_has_diff_to_review_section(launch_phase: str):
    """launch.md has a Diff to Review prompt template section."""
    assert "## Diff to Review" in launch_phase


def test_shared_contracts_references_slicing(shared_contracts: str):
    """shared-contracts.md references slicing.md for content slicing contracts."""
    assert "slicing.md" in shared_contracts


def test_synthesize_references_slicing(synthesize_phase: str):
    """synthesize.md references slicing.md for slicing awareness and reporting."""
    assert "slicing.md" in synthesize_phase
