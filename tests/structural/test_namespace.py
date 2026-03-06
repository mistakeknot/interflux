"""Tests to verify interflux namespace is correct (no stale clavain: refs)."""

from pathlib import Path

import pytest


def _scan_files(root: Path, glob_pattern: str = "**/*.md") -> list[tuple[Path, int, str]]:
    """Scan files for stale clavain: references that should be interflux:."""
    stale_patterns = [
        "clavain:review:fd-",
        "clavain:flux-drive",
        "clavain:flux-gen",
        "mcp__plugin_clavain_qmd__",
        "Plugin Agents (clavain)",
    ]
    findings = []
    for path in root.rglob(glob_pattern):
        if "docs/research" in str(path):
            continue  # skip historical archives
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            for pattern in stale_patterns:
                if pattern in line:
                    findings.append((path.relative_to(root), i, pattern))
    return findings


def test_no_stale_clavain_refs_in_skills(project_root: Path):
    """No stale clavain: namespace refs in skills/."""
    findings = _scan_files(project_root / "skills")
    assert findings == [], f"Stale clavain: refs found: {findings}"


def test_no_stale_clavain_refs_in_agents(project_root: Path):
    """No stale clavain: namespace refs in agents/."""
    findings = _scan_files(project_root / "agents")
    assert findings == [], f"Stale clavain: refs found: {findings}"


def test_no_stale_clavain_refs_in_commands(project_root: Path):
    """No stale clavain: namespace refs in commands/."""
    findings = _scan_files(project_root / "commands")
    assert findings == [], f"Stale clavain: refs found: {findings}"


def test_agent_roster_uses_interflux_namespace(project_root: Path):
    """Agent roster uses interflux:review:fd-* namespace."""
    roster = (project_root / "skills" / "flux-drive" / "references" / "agent-roster.md").read_text()
    assert "interflux:review:fd-architecture" in roster
    assert "interflux:review:fd-safety" in roster
    assert "Plugin Agents (interflux)" in roster


def test_launch_uses_interknow_mcp(project_root: Path):
    """launch.md uses mcp__plugin_interknow_qmd__ prefix (qmd moved to interknow)."""
    launch = (project_root / "skills" / "flux-drive" / "phases" / "launch.md").read_text()
    assert "mcp__plugin_interknow_qmd__" in launch
    assert "mcp__plugin_clavain_qmd__" not in launch


def test_launch_uses_interknow_collection(project_root: Path):
    """launch.md uses interknow qmd collection name."""
    launch = (project_root / "skills" / "flux-drive" / "phases" / "launch.md").read_text()
    assert '"interknow"' in launch


def test_flux_drive_command_uses_interflux(project_root: Path):
    """flux-drive command references interflux:flux-drive skill."""
    cmd = (project_root / "commands" / "flux-drive.md").read_text()
    assert "interflux:flux-drive" in cmd


def test_flux_drive_command_no_phase_tracking(project_root: Path):
    """flux-drive command does NOT contain lib-gates.sh sourcing."""
    cmd = (project_root / "commands" / "flux-drive.md").read_text()
    assert "lib-gates.sh" not in cmd
