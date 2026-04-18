"""Tests for interflux skill structure."""

from pathlib import Path

import pytest

from helpers import parse_frontmatter


SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"
SKILL_DIRS = sorted(
    d for d in SKILLS_DIR.iterdir()
    if d.is_dir() and (d / "SKILL.md").exists()
)


def test_skill_count(skills_dir):
    """Total skill count matches expected value."""
    dirs = sorted(
        d for d in skills_dir.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )
    assert len(dirs) == 1, (
        f"Expected 1 skill, found {len(dirs)}: {[d.name for d in dirs]}"
    )


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_skill_has_skillmd(skill_dir):
    """Each skill directory has a SKILL.md file."""
    assert (skill_dir / "SKILL.md").exists()


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_skill_has_frontmatter(skill_dir):
    """Each SKILL.md has valid YAML frontmatter with 'name' and 'description'."""
    fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
    assert fm is not None, f"{skill_dir.name}/SKILL.md has no frontmatter"
    assert "name" in fm, f"{skill_dir.name}/SKILL.md frontmatter missing 'name'"
    assert "description" in fm, f"{skill_dir.name}/SKILL.md frontmatter missing 'description'"


def test_flux_drive_phases_exist(skills_dir):
    """flux-drive skill has all expected phase files."""
    phases_dir = skills_dir / "flux-drive" / "phases"
    expected = ["launch.md", "synthesize.md", "shared-contracts.md", "slicing.md", "cross-ai.md", "launch-codex.md"]
    for name in expected:
        assert (phases_dir / name).exists(), f"Missing phase: {name}"


def test_flux_drive_references_exist(skills_dir):
    """flux-drive skill has reference files."""
    refs_dir = skills_dir / "flux-drive" / "references"
    expected = ["agent-roster.md", "scoring-examples.md"]
    for name in expected:
        assert (refs_dir / name).exists(), f"Missing reference: {name}"


def test_flux_research_skill_removed(skills_dir):
    """flux-research skill directory was removed in v0.2.61.
    The command commands/flux-research.md now routes to flux-drive with mode=research."""
    assert not (skills_dir / "flux-research").exists(), (
        "flux-research/ skill directory should be removed — it was deprecated in v0.2.56 "
        "and scheduled for deletion in v0.2.61. Routing is now handled by commands/"
        "flux-research.md forwarding to /interflux:flux-drive with mode=research."
    )
