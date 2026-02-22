"""Tests for scripts/generate-agents.py agent generation."""

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
generate = _mod.generate
parse_agent_specs = _mod.parse_agent_specs
render_agent = _mod.render_agent

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "generate-agents.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_PROFILE = dedent("""\
    # Test Domain Profile

    ## Detection Signals

    Some signals here.

    ## Agent Specifications

    These are domain-specific agents for testing.

    ### fd-alpha-checker

    Focus: Alpha channel validation and transparency handling.

    Persona: You are an alpha channel specialist — pixel-perfect and uncompromising.

    Decision lens: Prefer fixes that preserve visual fidelity over performance shortcuts.

    Key review areas:
    - Check alpha blending uses premultiplied alpha consistently across the pipeline.
    - Verify transparent regions do not cause z-fighting artifacts in composited output.
    - Validate export formats preserve alpha channel data without lossy compression.
    - Confirm fallback rendering for surfaces without alpha support is visually acceptable.
    - Ensure alpha test thresholds are tunable and documented for each material type.

    Success criteria hints:
    - Provide specific pixel coordinates or regions when flagging alpha artifacts
    - Include before/after screenshots for visual regression findings

    ### fd-beta-validator

    Focus: Beta testing workflows and feedback collection.

    Key review areas:
    - Check that feedback forms capture structured data for triage.
    - Verify crash reporters include sufficient context for reproduction.
    - Validate analytics events fire at documented touchpoints.
    - Confirm opt-in consent flows meet platform requirements.
    - Ensure beta build distribution channels are access-controlled.

    ## Research Directives

    Some research stuff.
""")

MOCK_PROFILE_WITH_CORE = dedent("""\
    # Core Domain Profile

    ## Agent Specifications

    ### fd-architecture

    Focus: System architecture and module boundaries.

    Key review areas:
    - Check module boundaries.

    ### fd-real-agent

    Focus: Real agent work.

    Key review areas:
    - Check real things.
    - Verify real stuff.

    ### fd-safety

    Focus: Security vulnerabilities.

    Key review areas:
    - Check credentials.
""")

MOCK_PROFILE_NO_SPECS = dedent("""\
    # Bare Domain Profile

    ## Detection Signals

    Some signals.

    ## Research Directives

    Some research.
""")


def _write_profile(tmp_path: Path, filename: str, content: str) -> Path:
    """Write a mock profile and return its path."""
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


def _setup_cache(project: Path, domains: list[dict]) -> None:
    """Write a flux-drive.yaml cache in the project."""
    cache_dir = project / ".claude"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "flux-drive.yaml"
    data = {
        "cache_version": 1,
        "domains": domains,
        "detected_at": "2026-02-22T00:00:00+00:00",
    }
    cache_path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def _write_existing_agent(agents_dir: Path, name: str, domain: str, version: int = 4) -> None:
    """Write a minimal generated agent file."""
    agents_dir.mkdir(parents=True, exist_ok=True)
    content = dedent(f"""\
        ---
        generated_by: flux-gen
        domain: {domain}
        generated_at: '2026-01-01T00:00:00+00:00'
        flux_gen_version: {version}
        ---
        # {name} — Test Domain Reviewer
    """)
    (agents_dir / f"{name}.md").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# TestParseAgentSpecs
# ---------------------------------------------------------------------------

class TestParseAgentSpecs:
    def test_extracts_agent_from_profile(self, tmp_path):
        """Parse a mock profile, verify 2 agents extracted with correct fields."""
        profile = _write_profile(tmp_path, "test-domain.md", MOCK_PROFILE)
        specs = parse_agent_specs(profile, "test-domain")

        assert len(specs) == 2

        alpha = specs[0]
        assert alpha["name"] == "fd-alpha-checker"
        assert alpha["domain"] == "test-domain"
        assert "Alpha channel" in alpha["focus"]
        assert alpha["persona"] is not None
        assert "pixel-perfect" in alpha["persona"]
        assert alpha["decision_lens"] is not None
        assert len(alpha["review_areas"]) == 5
        assert len(alpha["success_hints"]) == 2

        beta = specs[1]
        assert beta["name"] == "fd-beta-validator"
        assert beta["domain"] == "test-domain"
        assert "Beta testing" in beta["focus"]
        assert beta["persona"] is None  # no persona line
        assert beta["decision_lens"] is None  # no decision lens line
        assert len(beta["review_areas"]) == 5
        assert len(beta["success_hints"]) == 0

    def test_skips_core_agent_injections(self, tmp_path):
        """Core agents (fd-architecture etc) are skipped."""
        profile = _write_profile(tmp_path, "core-domain.md", MOCK_PROFILE_WITH_CORE)
        specs = parse_agent_specs(profile, "core-domain")

        names = [s["name"] for s in specs]
        assert "fd-architecture" not in names
        assert "fd-safety" not in names
        assert "fd-real-agent" in names
        assert len(specs) == 1

    def test_no_agent_specs_section(self, tmp_path):
        """Profile without Agent Specifications returns empty list."""
        profile = _write_profile(tmp_path, "bare.md", MOCK_PROFILE_NO_SPECS)
        specs = parse_agent_specs(profile, "bare-domain")
        assert specs == []


# ---------------------------------------------------------------------------
# TestRenderAgent
# ---------------------------------------------------------------------------

class TestRenderAgent:
    def _make_spec(self, **overrides) -> dict:
        base = {
            "name": "fd-test-agent",
            "domain": "test-domain",
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
        # Parse frontmatter
        end = content.index("---", 3)
        fm = yaml.safe_load(content[3:end])

        assert fm["generated_by"] == "flux-gen"
        assert fm["domain"] == "test-domain"
        assert fm["flux_gen_version"] == FLUX_GEN_VERSION
        assert "generated_at" in fm

    def test_persona_fallback(self):
        """When persona is None, a fallback is generated from focus and domain."""
        spec = self._make_spec(persona=None, focus="Test focus area.", domain="test-domain")
        content = render_agent(spec)

        # Fallback pattern: "You are a {domain} {focus} specialist"
        assert "test domain" in content.lower()
        assert "specialist" in content.lower()
        # Should not contain "None"
        assert "None" not in content

    def test_decision_lens_fallback(self):
        """When decision_lens is None, a fallback is generated."""
        spec = self._make_spec(decision_lens=None, domain="test-domain")
        content = render_agent(spec)

        assert "Prioritize findings by real-world impact" in content
        assert "test domain" in content.lower()

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
        assert "Check that tests cover all branches." in content
        assert "Verify mocks match real interfaces." in content
        assert "Ensure coverage reports are generated." in content

    def test_success_hints_appended(self):
        """Success criteria hints from spec appear in Success Criteria section."""
        spec = self._make_spec(
            success_hints=["Include stack traces for crash findings"],
        )
        content = render_agent(spec)
        assert "Include stack traces for crash findings" in content

    def test_what_not_to_flag_section(self):
        """What NOT to Flag section references core agents."""
        spec = self._make_spec()
        content = render_agent(spec)
        assert "fd-architecture handles this" in content
        assert "fd-safety handles this" in content
        assert "fd-correctness handles this" in content

    def test_title_format(self):
        """Title uses agent name and domain display name."""
        spec = self._make_spec(name="fd-test-agent", domain="game-simulation")
        content = render_agent(spec)
        assert "# fd-test-agent — Game Simulation Domain Reviewer" in content


# ---------------------------------------------------------------------------
# TestGenerate
# ---------------------------------------------------------------------------

class TestGenerate:
    def test_no_domains_returns_no_domains(self, tmp_path):
        """No cache -> status: no_domains."""
        report = generate(tmp_path)
        assert report["status"] == "no_domains"

    def test_skip_existing_mode(self, tmp_path, monkeypatch):
        """Existing agents are preserved in skip-existing mode."""
        # We need to mock DOMAINS_DIR to point to our test profiles
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "test-domain.md", MOCK_PROFILE)
        monkeypatch.setattr(_mod, "DOMAINS_DIR", profiles_dir)

        project = tmp_path / "project"
        project.mkdir()
        _setup_cache(project, [{"name": "test-domain", "confidence": 0.8}])

        agents_dir = project / ".claude" / "agents"
        _write_existing_agent(agents_dir, "fd-alpha-checker", "test-domain", version=FLUX_GEN_VERSION)

        report = generate(project, mode="skip-existing")

        assert report["status"] == "ok"
        assert "fd-alpha-checker" in report["skipped"]
        assert "fd-beta-validator" in report["generated"]

    def test_regenerate_stale_mode(self, tmp_path, monkeypatch):
        """Old version agents are regenerated in regenerate-stale mode."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "test-domain.md", MOCK_PROFILE)
        monkeypatch.setattr(_mod, "DOMAINS_DIR", profiles_dir)

        project = tmp_path / "project"
        project.mkdir()
        _setup_cache(project, [{"name": "test-domain", "confidence": 0.8}])

        agents_dir = project / ".claude" / "agents"
        # Write with old version — should be regenerated
        _write_existing_agent(agents_dir, "fd-alpha-checker", "test-domain", version=2)
        # Write with current version — should be skipped
        _write_existing_agent(agents_dir, "fd-beta-validator", "test-domain", version=FLUX_GEN_VERSION)

        report = generate(project, mode="regenerate-stale")

        assert report["status"] == "ok"
        assert "fd-alpha-checker" in report["generated"]
        assert "fd-beta-validator" in report["skipped"]

    def test_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        """Dry run reports but doesn't write any files."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "test-domain.md", MOCK_PROFILE)
        monkeypatch.setattr(_mod, "DOMAINS_DIR", profiles_dir)

        project = tmp_path / "project"
        project.mkdir()
        _setup_cache(project, [{"name": "test-domain", "confidence": 0.8}])

        report = generate(project, mode="force", dry_run=True)

        assert report["status"] == "ok"
        assert len(report["generated"]) == 2

        # No agent files should exist
        agents_dir = project / ".claude" / "agents"
        if agents_dir.exists():
            agent_files = list(agents_dir.glob("fd-*.md"))
            assert len(agent_files) == 0

    def test_orphan_detection(self, tmp_path, monkeypatch):
        """Agents for removed domains reported as orphaned."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "test-domain.md", MOCK_PROFILE)
        monkeypatch.setattr(_mod, "DOMAINS_DIR", profiles_dir)

        project = tmp_path / "project"
        project.mkdir()
        # Cache only has test-domain
        _setup_cache(project, [{"name": "test-domain", "confidence": 0.8}])

        # But we have an agent for a different domain
        agents_dir = project / ".claude" / "agents"
        _write_existing_agent(agents_dir, "fd-old-agent", "removed-domain", version=3)

        report = generate(project, mode="skip-existing")

        assert report["status"] == "ok"
        assert "fd-old-agent" in report["orphaned"]

    def test_force_mode_overwrites(self, tmp_path, monkeypatch):
        """Force mode regenerates even current-version agents."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "test-domain.md", MOCK_PROFILE)
        monkeypatch.setattr(_mod, "DOMAINS_DIR", profiles_dir)

        project = tmp_path / "project"
        project.mkdir()
        _setup_cache(project, [{"name": "test-domain", "confidence": 0.8}])

        agents_dir = project / ".claude" / "agents"
        _write_existing_agent(agents_dir, "fd-alpha-checker", "test-domain", version=FLUX_GEN_VERSION)

        report = generate(project, mode="force")

        assert report["status"] == "ok"
        assert "fd-alpha-checker" in report["generated"]
        assert "fd-alpha-checker" not in report["skipped"]

    def test_empty_cache_domains(self, tmp_path):
        """Cache with empty domains list -> no_domains."""
        project = tmp_path / "project"
        project.mkdir()
        cache_dir = project / ".claude"
        cache_dir.mkdir(parents=True)
        (cache_dir / "flux-drive.yaml").write_text(
            "domains: []\n", encoding="utf-8",
        )
        report = generate(project)
        assert report["status"] == "no_domains"


# ---------------------------------------------------------------------------
# TestCheckExistingAgents
# ---------------------------------------------------------------------------

class TestCheckExistingAgents:
    def test_finds_flux_gen_agents(self, tmp_path):
        """Only returns agents with generated_by: flux-gen."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        # flux-gen generated agent
        _write_existing_agent(agents_dir, "fd-gen-agent", "test-domain", version=3)

        # Manually created agent (no frontmatter match)
        (agents_dir / "fd-manual-agent.md").write_text(
            "# Manual Agent\n\nNo frontmatter.\n", encoding="utf-8",
        )

        # fd-* file with different generator
        (agents_dir / "fd-other-gen.md").write_text(
            "---\ngenerated_by: something-else\ndomain: test\n---\n# Other\n",
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
    def test_cli_json_output(self, tmp_path, monkeypatch):
        """Valid JSON from --json flag."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        _write_profile(profiles_dir, "test-domain.md", MOCK_PROFILE)

        project = tmp_path / "project"
        project.mkdir()
        _setup_cache(project, [{"name": "test-domain", "confidence": 0.8}])

        # We need to patch DOMAINS_DIR in the script's environment.
        # Since CLI runs as a subprocess, we create a wrapper that patches.
        # Instead, we use the Python API via subprocess with env var.
        # Simpler: just call generate() directly for JSON output test.
        # But the task says test CLI... let's use subprocess with a small script.
        #
        # Actually the simplest approach: create a test-domain.md profile
        # at the path the script expects.
        # The script uses PLUGIN_ROOT/config/flux-drive/domains/{domain}.md
        # We can't easily change that for subprocess tests.
        # Instead, we use an existing domain.
        project2 = tmp_path / "project2"
        project2.mkdir()
        _setup_cache(project2, [{"name": "game-simulation", "confidence": 0.8}])

        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project2), "--json", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "status" in data
        assert "generated" in data
        assert isinstance(data["generated"], list)

    def test_cli_no_cache_exits_1(self, tmp_path):
        """Exit code 1 when no cache exists."""
        project = tmp_path / "empty_project"
        project.mkdir()

        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project), "--json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1

    def test_cli_dry_run_creates_no_files(self, tmp_path):
        """--dry-run writes nothing to disk."""
        project = tmp_path / "project"
        project.mkdir()
        _setup_cache(project, [{"name": "game-simulation", "confidence": 0.8}])

        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project), "--dry-run", "--json"],
            capture_output=True, text=True, timeout=30,
        )

        assert result.returncode == 0
        agents_dir = project / ".claude" / "agents"
        if agents_dir.exists():
            agent_files = list(agents_dir.glob("fd-*.md"))
            assert len(agent_files) == 0
        # The report should list agents that would be generated
        data = json.loads(result.stdout)
        assert len(data["generated"]) > 0

    def test_cli_invalid_path_exits_2(self):
        """Exit code 2 for nonexistent project path."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "/nonexistent/path/xyz"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 2
