"""Tests for interflux command structure."""

from pathlib import Path

import pytest

from helpers import parse_frontmatter


COMMANDS_DIR = Path(__file__).resolve().parent.parent.parent / "commands"
COMMAND_FILES = sorted(COMMANDS_DIR.glob("*.md"))


def test_command_count(commands_dir):
    """Total command count matches expected value."""
    files = sorted(commands_dir.glob("*.md"))
    assert len(files) == 7, (
        f"Expected 7 commands, found {len(files)}: {[f.stem for f in files]}"
    )


@pytest.mark.parametrize("cmd_file", COMMAND_FILES, ids=lambda p: p.stem)
def test_command_has_frontmatter(cmd_file):
    """Each command .md has valid YAML frontmatter with 'name' and 'description'."""
    fm, _ = parse_frontmatter(cmd_file)
    assert fm is not None, f"{cmd_file.name} has no frontmatter"
    assert "name" in fm, f"{cmd_file.name} frontmatter missing 'name'"
    assert "description" in fm, f"{cmd_file.name} frontmatter missing 'description'"


def test_expected_commands_exist(commands_dir):
    """All expected commands exist."""
    assert (commands_dir / "flux-drive.md").exists()
    assert (commands_dir / "flux-gen.md").exists()
    assert (commands_dir / "flux-research.md").exists()
