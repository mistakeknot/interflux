"""Tests for scripts/generate-agents.py agent generation (specs-only mode)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

# Import the hyphenated module name via importlib
_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "generate-agents.py"
_spec = importlib.util.spec_from_file_location("generate_agents", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

FLUX_GEN_VERSION = _mod.FLUX_GEN_VERSION
check_existing_agents = _mod.check_existing_agents
generate_from_specs = _mod.generate_from_specs
render_agent = _mod.render_agent

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "generate-agents.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_SPECS = [
    {
        "name": "fd-alpha-checker",
        "focus": "Alpha channel validation and transparency handling.",
        "persona": "You are an alpha channel specialist — pixel-perfect and uncompromising.",
        "decision_lens": "Prefer fixes that preserve visual fidelity over performance shortcuts.",
        "review_areas": [
            "Check alpha blending uses premultiplied alpha consistently.",
            "Verify transparent regions do not cause z-fighting artifacts.",
            "Validate export formats preserve alpha channel data.",
        ],
        "success_hints": [
            "Provide specific pixel coordinates when flagging alpha artifacts",
        ],
        "task_context": "Reviewing a graphics rendering pipeline.",
        "anti_overlap": ["fd-beta-validator covers testing workflows"],
    },
    {
        "name": "fd-beta-validator",
        "focus": "Beta testing workflows and feedback collection.",
        "review_areas": [
            "Check that feedback forms capture structured data for triage.",
            "Verify crash reporters include sufficient context for reproduction.",
        ],
        "success_hints": [],
        "task_context": "Reviewing a graphics rendering pipeline.",
        "anti_overlap": ["fd-alpha-checker covers rendering correctness"],
    },
]


def _write_specs(tmp_path: Path, specs: list[dict] = None) -> Path:
    """Write specs JSON file and return its path."""
    specs_path = tmp_path / "specs.json"
    specs_path.write_text(json.dumps(specs or MOCK_SPECS), encoding="utf-8")
    return specs_path


def _write_existing_agent(agents_dir: Path, name: str, version: int = 4) -> None:
    """Write a minimal generated agent file."""
    agents_dir.mkdir(parents=True, exist_ok=True)
    content = dedent(f"""\
        ---
        generated_by: flux-gen-prompt
        generated_at: '2026-01-01T00:00:00+00:00'
        flux_gen_version: {version}
        ---
        # {name} — Task-Specific Reviewer
    """)
    (agents_dir / f"{name}.md").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# TestRenderAgent
# ---------------------------------------------------------------------------

class TestRenderAgent:
    def _make_spec(self, **overrides) -> dict:
        base = {
            "name": "fd-test-agent",
            "focus": "Test focus area.",
            "persona": "You are a test specialist — thorough and precise.",
            "decision_lens": "Prefer correctness over speed.",
            "review_areas": [
                "Check that tests cover all branches.",
                "Verify mocks match real interfaces.",
            ],
            "success_hints": [],
        }
        base.update(overrides)
        return base

    def test_renders_frontmatter(self):
        """Verify YAML frontmatter fields are present and correct."""
        spec = self._make_spec()
        content = render_agent(spec)

        assert content.startswith("---\n")
        end = content.index("---", 3)
        fm = yaml.safe_load(content[3:end])

        assert fm["generated_by"] == "flux-gen-prompt"
        assert fm["flux_gen_version"] == FLUX_GEN_VERSION
        assert "generated_at" in fm

    def test_persona_fallback(self):
        """When persona is None, a fallback is generated from focus."""
        spec = self._make_spec(persona=None, focus="Test focus area.")
        content = render_agent(spec)

        assert "specialist" in content.lower()
        assert "None" not in content

    def test_decision_lens_fallback(self):
        """When decision_lens is None, a fallback is generated."""
        spec = self._make_spec(decision_lens=None)
        content = render_agent(spec)

        assert "Prioritize findings by real-world impact" in content

    def test_review_areas_rendered(self):
        """Review areas appear as numbered sections in Review Approach."""
        spec = self._make_spec(
            review_areas=[
                "Check that tests cover all branches.",
                "Verify mocks match real interfaces.",
                "Ensure coverage reports are generated.",
            ],
        )
        content = render_agent(spec)

        assert "### 1." in content
        assert "### 2." in content
        assert "### 3." in content

    def test_success_hints_appended(self):
        """Success criteria hints from spec appear in Success Criteria section."""
        spec = self._make_spec(
            success_hints=["Include stack traces for crash findings"],
        )
        content = render_agent(spec)
        assert "Include stack traces for crash findings" in content

    def test_anti_overlap_section(self):
        """Anti-overlap entries produce What NOT to Flag section."""
        spec = self._make_spec(
            anti_overlap=["fd-other covers architecture"],
        )
        content = render_agent(spec)
        assert "What NOT to Flag" in content
        assert "fd-other covers architecture" in content

    def test_task_context_section(self):
        """Task context is rendered when present."""
        spec = self._make_spec(task_context="Reviewing a critical auth module.")
        content = render_agent(spec)
        assert "## Task Context" in content
        assert "Reviewing a critical auth module." in content


# ---------------------------------------------------------------------------
# TestGenerateFromSpecs
# ---------------------------------------------------------------------------

class TestGenerateFromSpecs:
    def test_generates_agents(self, tmp_path):
        """Specs produce agent files."""
        project = tmp_path / "project"
        project.mkdir()
        specs_path = _write_specs(tmp_path)

        report = generate_from_specs(project, specs_path)

        assert report["status"] == "ok"
        assert "fd-alpha-checker" in report["generated"]
        assert "fd-beta-validator" in report["generated"]

        agents_dir = project / ".claude" / "agents"
        assert (agents_dir / "fd-alpha-checker.md").exists()
        assert (agents_dir / "fd-beta-validator.md").exists()

    def test_skip_existing_mode(self, tmp_path):
        """Existing agents are preserved in skip-existing mode."""
        project = tmp_path / "project"
        project.mkdir()
        specs_path = _write_specs(tmp_path)

        agents_dir = project / ".claude" / "agents"
        _write_existing_agent(agents_dir, "fd-alpha-checker", version=FLUX_GEN_VERSION)

        report = generate_from_specs(project, specs_path, mode="skip-existing")

        assert report["status"] == "ok"
        assert "fd-alpha-checker" in report["skipped"]
        assert "fd-beta-validator" in report["generated"]

    def test_regenerate_stale_mode(self, tmp_path):
        """Old version agents are regenerated in regenerate-stale mode."""
        project = tmp_path / "project"
        project.mkdir()
        specs_path = _write_specs(tmp_path)

        agents_dir = project / ".claude" / "agents"
        _write_existing_agent(agents_dir, "fd-alpha-checker", version=2)
        _write_existing_agent(agents_dir, "fd-beta-validator", version=FLUX_GEN_VERSION)

        report = generate_from_specs(project, specs_path, mode="regenerate-stale")

        assert report["status"] == "ok"
        assert "fd-alpha-checker" in report["generated"]
        assert "fd-beta-validator" in report["skipped"]

    def test_force_mode_overwrites(self, tmp_path):
        """Force mode regenerates even current-version agents."""
        project = tmp_path / "project"
        project.mkdir()
        specs_path = _write_specs(tmp_path)

        agents_dir = project / ".claude" / "agents"
        _write_existing_agent(agents_dir, "fd-alpha-checker", version=FLUX_GEN_VERSION)

        report = generate_from_specs(project, specs_path, mode="force")

        assert report["status"] == "ok"
        assert "fd-alpha-checker" in report["generated"]

    def test_dry_run_writes_nothing(self, tmp_path):
        """Dry run reports but doesn't write any files."""
        project = tmp_path / "project"
        project.mkdir()
        specs_path = _write_specs(tmp_path)

        report = generate_from_specs(project, specs_path, mode="force", dry_run=True)

        assert report["status"] == "ok"
        assert len(report["generated"]) == 2

        agents_dir = project / ".claude" / "agents"
        if agents_dir.exists():
            assert len(list(agents_dir.glob("fd-*.md"))) == 0

    def test_skips_core_agents(self, tmp_path):
        """Core agent names are rejected."""
        project = tmp_path / "project"
        project.mkdir()
        specs = [{"name": "fd-architecture", "focus": "test", "review_areas": []}]
        specs_path = _write_specs(tmp_path, specs)

        report = generate_from_specs(project, specs_path)

        assert "fd-architecture" not in report["generated"]
        assert any("conflicts with core agent" in e for e in report["errors"])

    def test_skips_invalid_names(self, tmp_path):
        """Names not starting with fd- are rejected."""
        project = tmp_path / "project"
        project.mkdir()
        specs = [{"name": "bad-name", "focus": "test", "review_areas": []}]
        specs_path = _write_specs(tmp_path, specs)

        report = generate_from_specs(project, specs_path)

        assert "bad-name" not in report["generated"]
        assert any("must start with 'fd-'" in e for e in report["errors"])

    def test_invalid_json(self, tmp_path):
        """Invalid JSON specs produce error status."""
        project = tmp_path / "project"
        project.mkdir()
        specs_path = tmp_path / "bad.json"
        specs_path.write_text("not json{", encoding="utf-8")

        report = generate_from_specs(project, specs_path)

        assert report["status"] == "error"

    def test_non_array_json(self, tmp_path):
        """Non-array JSON produces error status."""
        project = tmp_path / "project"
        project.mkdir()
        specs_path = tmp_path / "obj.json"
        specs_path.write_text('{"not": "array"}', encoding="utf-8")

        report = generate_from_specs(project, specs_path)

        assert report["status"] == "error"


# ---------------------------------------------------------------------------
# TestCheckExistingAgents
# ---------------------------------------------------------------------------

class TestCheckExistingAgents:
    def test_finds_flux_gen_agents(self, tmp_path):
        """Only returns agents with generated_by: flux-gen or flux-gen-prompt."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        _write_existing_agent(agents_dir, "fd-gen-agent", version=3)

        # Manually created agent (no frontmatter match)
        (agents_dir / "fd-manual-agent.md").write_text(
            "# Manual Agent\n\nNo frontmatter.\n", encoding="utf-8",
        )

        # fd-* file with different generator
        (agents_dir / "fd-other-gen.md").write_text(
            "---\ngenerated_by: something-else\n---\n# Other\n",
            encoding="utf-8",
        )

        result = check_existing_agents(agents_dir)
        assert "fd-gen-agent" in result
        assert "fd-manual-agent" not in result
        assert "fd-other-gen" not in result

    def test_nonexistent_dir(self, tmp_path):
        """Non-existent agents dir returns empty dict."""
        result = check_existing_agents(tmp_path / "nonexistent")
        assert result == {}


# ---------------------------------------------------------------------------
# TestCLIIntegration
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    def test_cli_requires_from_specs(self, tmp_path):
        """CLI exits with error when --from-specs not provided."""
        project = tmp_path / "project"
        project.mkdir()

        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 2

    def test_cli_json_output(self, tmp_path):
        """Valid JSON from --json flag."""
        project = tmp_path / "project"
        project.mkdir()
        specs_path = _write_specs(tmp_path)

        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project), "--from-specs", str(specs_path), "--json", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "status" in data
        assert "generated" in data
        assert len(data["generated"]) == 2

    def test_cli_missing_specs_exits_2(self, tmp_path):
        """Exit code 2 when specs file doesn't exist."""
        project = tmp_path / "project"
        project.mkdir()

        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project), "--from-specs", "/nonexistent/specs.json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 2

    def test_cli_invalid_path_exits_2(self):
        """Exit code 2 for nonexistent project path."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "/nonexistent/path/xyz", "--from-specs", "/tmp/x.json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 2
