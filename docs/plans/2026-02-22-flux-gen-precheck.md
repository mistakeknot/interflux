# Flux-Gen Pre-Check + LLM Domain Detection Implementation Plan
**Phase:** executing (as of 2026-02-22T18:29:36Z)

> **For Claude:** REQUIRED SUB-SKILL: Use clavain:executing-plans to implement this plan task-by-task.

**Goal:** Replace heuristic domain detection with LLM-based classification and extract agent generation into a deterministic shared Python script.

**Architecture:** Two-layer pipeline: (1) LLM-based detection runs a Haiku subagent to classify the project into known domains, caches results with content hashes for staleness; (2) deterministic `generate-agents.py` reads cached domains + domain profile markdown, templates agent files. Both flux-drive and flux-gen invoke this shared pipeline. Heuristic scoring stays as offline fallback.

**Tech Stack:** Python 3.14, PyYAML, pytest, Claude Haiku (via Task tool), markdown regex parsing

---

### Task 1: Create `generate-agents.py` — Core Template Engine

**Files:**
- Create: `interverse/interflux/scripts/generate-agents.py`

**Step 1: Write the failing test**

Create the test file first. It tests that the script can parse a domain profile's `## Agent Specifications` section and extract agent specs.

```python
# interverse/interflux/tests/structural/test_generate_agents.py
"""Tests for scripts/generate-agents.py agent generation."""

import importlib.util
import json
import textwrap
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "generate-agents.py"
_spec = importlib.util.spec_from_file_location("generate_agents", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

parse_agent_specs = _mod.parse_agent_specs
AGENT_TEMPLATE_VERSION = _mod.AGENT_TEMPLATE_VERSION


class TestParseAgentSpecs:
    def test_extracts_agent_from_profile(self, tmp_path):
        """Parse a domain profile and extract fd-* agent specs."""
        profile = tmp_path / "game-simulation.md"
        profile.write_text(textwrap.dedent("""\
            # Game Simulation Domain Profile

            ## Detection Signals
            Some signals here.

            ## Agent Specifications

            ### fd-simulation-kernel

            Focus: Tick loop architecture, determinism.

            Persona: You are a simulation engine specialist.

            Decision lens: Prefer determinism over performance.

            Key review areas:
            - Check timestep logic uses stable integration.
            - Verify system update order is deterministic.

            ### fd-game-systems

            Focus: Individual game system design.

            Key review areas:
            - Check system boundaries minimize coupling.
            - Verify sinks and faucets keep resources balanced.
        """))
        specs = parse_agent_specs(profile, "game-simulation")
        assert len(specs) == 2
        assert specs[0]["name"] == "fd-simulation-kernel"
        assert specs[0]["focus"] == "Tick loop architecture, determinism."
        assert specs[0]["persona"] == "You are a simulation engine specialist."
        assert specs[0]["decision_lens"] == "Prefer determinism over performance."
        assert len(specs[0]["review_areas"]) == 2
        assert specs[1]["name"] == "fd-game-systems"
        assert specs[1]["focus"] == "Individual game system design."
        # No persona in second spec — should be None
        assert specs[1]["persona"] is None

    def test_skips_core_agent_injections(self, tmp_path):
        """Agent specs that match core agents (fd-architecture, etc.) are skipped."""
        profile = tmp_path / "web-api.md"
        profile.write_text(textwrap.dedent("""\
            # Web API Domain Profile

            ## Agent Specifications

            ### fd-architecture
            - Check API layering.

            ### fd-api-contract
            Focus: API contract validation.
            Key review areas:
            - Check OpenAPI spec accuracy.
        """))
        specs = parse_agent_specs(profile, "web-api")
        assert len(specs) == 1
        assert specs[0]["name"] == "fd-api-contract"

    def test_no_agent_specs_section(self, tmp_path):
        """Profile without Agent Specifications returns empty list."""
        profile = tmp_path / "empty.md"
        profile.write_text("# Empty\n\n## Detection Signals\nNothing here.\n")
        specs = parse_agent_specs(profile, "empty")
        assert specs == []
```

**Step 2: Run test to verify it fails**

Run: `cd /home/mk/projects/Demarch/interverse/interflux && uv run --directory tests pytest tests/structural/test_generate_agents.py -v`
Expected: FAIL — `generate-agents.py` does not exist yet

**Step 3: Write the script with parse_agent_specs**

Create `interverse/interflux/scripts/generate-agents.py`:

```python
#!/usr/bin/env python3
"""Generate project-specific review agents from domain profiles.

Reads cached domain detection results and domain profile markdown files,
then writes .claude/agents/fd-*.md agent files deterministically.

Exit codes:
    0  Agents generated (or all up-to-date)
    1  No domains in cache (nothing to generate)
    2  Script error (missing profiles, parse failure)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("Error: pyyaml required – pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DOMAINS_DIR = PLUGIN_ROOT / "config" / "flux-drive" / "domains"

# Bump when template format changes — agents with older versions get regenerated
AGENT_TEMPLATE_VERSION = 4

# Core agents that get injection criteria, not standalone generation
CORE_AGENTS = {
    "fd-architecture", "fd-safety", "fd-correctness",
    "fd-quality", "fd-performance", "fd-user-product",
    "fd-game-design",
}

# Domain-specific doc types for the First Step section
DOMAIN_DOC_TYPES = {
    "game-simulation": "Game design documents (GDD), balance spreadsheets, system design docs",
    "web-api": "API specs (OpenAPI/Swagger), architecture decision records, runbooks",
    "ml-pipeline": "Model cards, experiment tracking docs, data lineage docs",
    "cli-tool": "Man pages, help text source, CLI design docs",
    "mobile-app": "Platform guidelines docs, accessibility docs, release checklists",
    "embedded-systems": "Hardware specs, memory maps, timing constraint docs",
    "data-pipeline": "Schema docs, data dictionaries, SLA definitions",
    "library-sdk": "API reference docs, migration guides, changelog",
    "tui-app": "Keybinding docs, accessibility docs, terminal compatibility notes",
    "desktop-tauri": "Platform integration docs, packaging configs, update channel docs",
    "claude-code-plugin": "Plugin manifest, skill/agent/command inventories, hook documentation",
}


def parse_agent_specs(profile_path: Path, domain: str) -> list[dict[str, Any]]:
    """Extract agent specifications from a domain profile markdown file.

    Parses the '## Agent Specifications' section, extracting each '### fd-*'
    subsection. Skips core agents (they get injection criteria, not standalone files).

    Returns list of dicts with keys: name, domain, focus, persona, decision_lens,
    review_areas (list of strings), success_criteria_hints (list or None).
    """
    text = profile_path.read_text(encoding="utf-8")

    # Find the Agent Specifications section
    match = re.search(r"^## Agent Specifications\s*\n", text, re.MULTILINE)
    if not match:
        return []

    # Extract from that section to the next ## heading or end of file
    rest = text[match.end():]
    next_h2 = re.search(r"^## ", rest, re.MULTILINE)
    if next_h2:
        rest = rest[:next_h2.start()]

    # Split into ### fd-* subsections
    agents: list[dict[str, Any]] = []
    parts = re.split(r"^### (fd-[\w-]+)\s*\n", rest, flags=re.MULTILINE)
    # parts[0] is preamble (before first ###), then alternating name, body
    for i in range(1, len(parts), 2):
        name = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""

        if name in CORE_AGENTS:
            continue

        spec: dict[str, Any] = {
            "name": name,
            "domain": domain,
            "focus": None,
            "persona": None,
            "decision_lens": None,
            "review_areas": [],
            "success_criteria_hints": None,
        }

        # Extract fields from body
        for line in body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("Focus:"):
                spec["focus"] = stripped[len("Focus:"):].strip()
            elif stripped.startswith("Persona:"):
                spec["persona"] = stripped[len("Persona:"):].strip()
            elif stripped.startswith("Decision lens:"):
                spec["decision_lens"] = stripped[len("Decision lens:"):].strip()

        # Extract review areas (bullet list after "Key review areas:")
        review_match = re.search(
            r"Key review areas:\s*\n((?:- .+\n?)+)", body
        )
        if review_match:
            spec["review_areas"] = [
                line.lstrip("- ").strip()
                for line in review_match.group(1).strip().split("\n")
                if line.strip().startswith("-")
            ]

        # Extract success criteria hints
        hints_match = re.search(
            r"Success criteria hints:\s*\n((?:- .+\n?)+)", body
        )
        if hints_match:
            spec["success_criteria_hints"] = [
                line.lstrip("- ").strip()
                for line in hints_match.group(1).strip().split("\n")
                if line.strip().startswith("-")
            ]

        if spec["focus"]:  # Only include specs that have at least a Focus line
            agents.append(spec)

    return agents


def read_domain_cache(project: Path) -> list[dict[str, Any]] | None:
    """Read cached domain detection results from .claude/flux-drive.yaml."""
    cache_path = project / ".claude" / "flux-drive.yaml"
    if not cache_path.exists():
        return None
    try:
        data = yaml.safe_load(cache_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("domains"):
            return data["domains"]
    except Exception:
        pass
    return None


def render_agent(spec: dict[str, Any]) -> str:
    """Render a single agent spec dict into the full agent .md file content."""
    domain = spec["domain"]
    domain_display = domain.replace("-", " ").title()
    name = spec["name"]
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    doc_types = DOMAIN_DOC_TYPES.get(domain, "Project documentation")

    # Persona fallback
    persona = spec.get("persona")
    if not persona:
        persona = (
            f"You are a {domain.replace('-', ' ')} {spec['focus'].rstrip('.')} "
            f"specialist — methodical, specific, and grounded in project reality."
        )

    # Decision lens fallback
    decision_lens = spec.get("decision_lens")
    if not decision_lens:
        decision_lens = (
            f"Prioritize findings by real-world impact on {domain.replace('-', ' ')} "
            f"projects. Flag issues that would cause failures in production before style concerns."
        )

    # Review approach sections
    review_sections = ""
    for i, area in enumerate(spec.get("review_areas", []), 1):
        # Derive short title from the first phrase
        short_title = area.split(".")[0].strip() if "." in area else area[:60]
        review_sections += f"\n### {i}. {short_title}\n\n- {area}\n"

    # Success criteria
    success_bullets = [
        "Ties every finding to a specific file, function, and line number — never a vague \"consider X\"",
        "Provides a concrete failure scenario for each P0/P1 finding — what breaks, under what conditions, and who is affected",
        "Recommends the smallest viable fix, not an architecture overhaul — one diff hunk, not a rewrite",
        "Distinguishes domain-specific expertise from generic code quality (defer the latter to core agents listed in \"What NOT to Flag\")",
        "Frames uncertain findings as questions: \"Does this handle X?\" not \"This doesn't handle X\"",
    ]
    if spec.get("success_criteria_hints"):
        success_bullets.extend(spec["success_criteria_hints"])
    success_text = "\n".join(f"- {b}" for b in success_bullets)

    return f"""---
generated_by: flux-gen
domain: {domain}
generated_at: '{now}'
flux_gen_version: {AGENT_TEMPLATE_VERSION}
---
# {name} — {domain_display} Domain Reviewer

> Generated by `/flux-gen` from the {domain} domain profile.
> Customize this file for your project's specific needs.

{persona}

## First Step (MANDATORY)

Check for project documentation:
1. `CLAUDE.md` in the project root
2. `AGENTS.md` in the project root
3. Domain-relevant docs: {doc_types}

If docs exist, operate in codebase-aware mode:
- Ground every finding in the project's actual patterns and conventions
- Reuse the project's terminology, not generic terms
- Avoid recommending changes the project has explicitly ruled out

If docs don't exist, operate in generic mode:
- Apply best practices for {domain.replace('-', ' ')} projects
- Mark assumptions explicitly so the team can correct them

## Review Approach
{review_sections}
## What NOT to Flag

- Architecture, module boundaries, or coupling concerns (fd-architecture handles this)
- Security vulnerabilities or credential handling (fd-safety handles this)
- Data consistency, race conditions, or transaction safety (fd-correctness handles this)
- Naming conventions, code style, or language idioms (fd-quality handles this)
- Rendering bottlenecks, algorithmic complexity, or memory usage (fd-performance handles this)
- User flows, UX friction, or value proposition (fd-user-product handles this)
- Only flag the above if they are deeply entangled with your domain expertise and the core agent would miss the domain-specific nuance

## Success Criteria

A good {domain.replace('-', ' ')} review:
{success_text}

## Decision Lens

{decision_lens}

When two fixes compete for attention, choose the one with higher real-world impact on {domain.replace('-', ' ')} concerns.

## Prioritization

- P0/P1: Issues that would cause failures, data loss, or broken functionality in production
- P2: Issues that degrade quality or create maintenance burden
- P3: Improvements and polish — suggest but don't block on these
- Always tie findings to specific files, functions, and line numbers
- Frame uncertain findings as questions, not assertions
"""


def check_existing_agents(agents_dir: Path) -> dict[str, dict[str, Any]]:
    """Read existing generated agents, return dict of name -> frontmatter."""
    existing: dict[str, dict[str, Any]] = {}
    if not agents_dir.exists():
        return existing
    for f in agents_dir.glob("fd-*.md"):
        try:
            text = f.read_text(encoding="utf-8")
            if text.startswith("---"):
                end = text.index("---", 3)
                fm = yaml.safe_load(text[3:end])
                if isinstance(fm, dict) and fm.get("generated_by") == "flux-gen":
                    existing[f.stem] = fm
        except Exception:
            continue
    return existing


def generate(
    project: Path,
    mode: str = "skip-existing",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Main generation logic. Returns a report dict."""
    domains = read_domain_cache(project)
    if not domains:
        return {"status": "no_domains", "agents": []}

    agents_dir = project / ".claude" / "agents"
    existing = check_existing_agents(agents_dir)

    report: dict[str, Any] = {"status": "ok", "agents": []}

    for domain_entry in domains:
        domain_name = domain_entry.get("profile") or domain_entry.get("name", "")
        if not domain_name:
            continue

        profile_path = DOMAINS_DIR / f"{domain_name}.md"
        if not profile_path.exists():
            report["agents"].append({
                "name": f"(profile missing: {domain_name})",
                "action": "failed",
                "reason": "domain profile not found",
            })
            continue

        specs = parse_agent_specs(profile_path, domain_name)
        for spec in specs:
            name = spec["name"]
            agent_report: dict[str, Any] = {"name": name, "domain": domain_name}

            if name in existing:
                existing_version = existing[name].get("flux_gen_version", 0)
                if mode == "skip-existing":
                    agent_report["action"] = "skipped"
                    agent_report["reason"] = "already exists"
                elif mode == "regenerate-stale":
                    if existing_version >= AGENT_TEMPLATE_VERSION:
                        agent_report["action"] = "skipped"
                        agent_report["reason"] = f"up-to-date (v{existing_version})"
                    else:
                        agent_report["action"] = "regenerated"
                        agent_report["reason"] = f"stale (v{existing_version} < v{AGENT_TEMPLATE_VERSION})"
                        if not dry_run:
                            _write_agent(agents_dir, name, spec)
                elif mode == "force":
                    agent_report["action"] = "regenerated"
                    agent_report["reason"] = "force mode"
                    if not dry_run:
                        _write_agent(agents_dir, name, spec)
            else:
                agent_report["action"] = "created"
                if not dry_run:
                    _write_agent(agents_dir, name, spec)

            report["agents"].append(agent_report)

    # Detect orphans: existing agents whose domain is no longer detected
    detected_domains = {
        (d.get("profile") or d.get("name", ""))
        for d in domains
    }
    for name, fm in existing.items():
        agent_domain = fm.get("domain", "")
        if agent_domain and agent_domain not in detected_domains:
            report["agents"].append({
                "name": name,
                "domain": agent_domain,
                "action": "orphaned",
                "reason": f"domain '{agent_domain}' no longer detected",
            })

    return report


def _write_agent(agents_dir: Path, name: str, spec: dict[str, Any]) -> None:
    """Write a single agent file atomically."""
    agents_dir.mkdir(parents=True, exist_ok=True)
    content = render_agent(spec).encode("utf-8")
    dest = agents_dir / f"{name}.md"
    fd, tmp = tempfile.mkstemp(dir=str(agents_dir), suffix=".tmp")
    try:
        os.write(fd, content)
        os.fsync(fd)
        os.close(fd)
        os.rename(tmp, str(dest))
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate project-specific review agents")
    parser.add_argument("project", type=Path, help="Project root directory")
    parser.add_argument("--mode", choices=["skip-existing", "regenerate-stale", "force"],
                        default="skip-existing", help="Generation mode")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output JSON report to stdout")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would happen without writing files")
    args = parser.parse_args()

    try:
        report = generate(args.project, mode=args.mode, dry_run=args.dry_run)
    except Exception as e:
        if args.json_output:
            json.dump({"status": "error", "error": str(e)}, sys.stdout)
        else:
            print(f"Error: {e}", file=sys.stderr)
        return 2

    if report["status"] == "no_domains":
        if args.json_output:
            json.dump(report, sys.stdout)
        else:
            print("No domains in cache. Run domain detection first.", file=sys.stderr)
        return 1

    if args.json_output:
        json.dump(report, sys.stdout, indent=2)
    else:
        for a in report["agents"]:
            print(f"  {a['action']:12s} {a['name']}: {a.get('reason', '')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/mk/projects/Demarch/interverse/interflux && uv run --directory tests pytest tests/structural/test_generate_agents.py -v`
Expected: PASS — all 3 tests

**Step 5: Commit**

```bash
git add scripts/generate-agents.py tests/structural/test_generate_agents.py
git commit -m "feat: add generate-agents.py — deterministic agent template engine"
```

---

### Task 2: Test `generate-agents.py` Generation Modes + Rendering

**Files:**
- Modify: `interverse/interflux/tests/structural/test_generate_agents.py`

**Step 1: Write failing tests for generation modes**

Add these test classes to the existing test file:

```python
render_agent = _mod.render_agent
generate = _mod.generate
check_existing_agents = _mod.check_existing_agents
AGENT_TEMPLATE_VERSION = _mod.AGENT_TEMPLATE_VERSION


class TestRenderAgent:
    def test_renders_frontmatter(self):
        spec = {
            "name": "fd-test-agent",
            "domain": "game-simulation",
            "focus": "Test focus.",
            "persona": "You are a test specialist.",
            "decision_lens": "Prefer tests.",
            "review_areas": ["Check A.", "Check B."],
            "success_criteria_hints": None,
        }
        output = render_agent(spec)
        assert "generated_by: flux-gen" in output
        assert "domain: game-simulation" in output
        assert f"flux_gen_version: {AGENT_TEMPLATE_VERSION}" in output
        assert "# fd-test-agent" in output
        assert "You are a test specialist." in output
        assert "Prefer tests." in output

    def test_persona_fallback(self):
        spec = {
            "name": "fd-test-agent",
            "domain": "web-api",
            "focus": "API validation.",
            "persona": None,
            "decision_lens": None,
            "review_areas": [],
            "success_criteria_hints": None,
        }
        output = render_agent(spec)
        assert "web api" in output.lower()
        assert "API validation" in output

    def test_review_areas_rendered(self):
        spec = {
            "name": "fd-test-agent",
            "domain": "cli-tool",
            "focus": "CLI design.",
            "persona": "You review CLIs.",
            "decision_lens": "Prefer simplicity.",
            "review_areas": ["Check flag consistency.", "Verify help text."],
            "success_criteria_hints": ["Include exit code in findings"],
        }
        output = render_agent(spec)
        assert "Check flag consistency" in output
        assert "Verify help text" in output
        assert "Include exit code in findings" in output


class TestGenerate:
    def test_no_domains_returns_no_domains(self, tmp_path):
        """No cache file → status: no_domains."""
        report = generate(tmp_path)
        assert report["status"] == "no_domains"

    def test_skip_existing_mode(self, tmp_path):
        """In skip-existing mode, existing agents are not overwritten."""
        # Create cache
        cache_dir = tmp_path / ".claude"
        cache_dir.mkdir()
        cache = {"domains": [{"profile": "game-simulation", "confidence": 0.8}]}
        (cache_dir / "flux-drive.yaml").write_text(
            yaml.dump(cache), encoding="utf-8"
        )
        # Create existing agent
        agents_dir = cache_dir / "agents"
        agents_dir.mkdir()
        (agents_dir / "fd-simulation-kernel.md").write_text(
            "---\ngenerated_by: flux-gen\ndomain: game-simulation\nflux_gen_version: 999\n---\nCustom content\n"
        )

        report = generate(tmp_path, mode="skip-existing")
        assert report["status"] == "ok"
        kernel_actions = [a for a in report["agents"] if a["name"] == "fd-simulation-kernel"]
        assert kernel_actions[0]["action"] == "skipped"
        # Custom content preserved
        assert "Custom content" in (agents_dir / "fd-simulation-kernel.md").read_text()

    def test_regenerate_stale_mode(self, tmp_path):
        """In regenerate-stale mode, old-version agents are regenerated."""
        cache_dir = tmp_path / ".claude"
        cache_dir.mkdir()
        cache = {"domains": [{"profile": "game-simulation", "confidence": 0.8}]}
        (cache_dir / "flux-drive.yaml").write_text(
            yaml.dump(cache), encoding="utf-8"
        )
        agents_dir = cache_dir / "agents"
        agents_dir.mkdir()
        (agents_dir / "fd-simulation-kernel.md").write_text(
            "---\ngenerated_by: flux-gen\ndomain: game-simulation\nflux_gen_version: 1\n---\nOld\n"
        )

        report = generate(tmp_path, mode="regenerate-stale")
        kernel_actions = [a for a in report["agents"] if a["name"] == "fd-simulation-kernel"]
        assert kernel_actions[0]["action"] == "regenerated"
        new_content = (agents_dir / "fd-simulation-kernel.md").read_text()
        assert "Old" not in new_content
        assert f"flux_gen_version: {AGENT_TEMPLATE_VERSION}" in new_content

    def test_dry_run_writes_nothing(self, tmp_path):
        """Dry run reports actions but doesn't write files."""
        cache_dir = tmp_path / ".claude"
        cache_dir.mkdir()
        cache = {"domains": [{"profile": "game-simulation", "confidence": 0.8}]}
        (cache_dir / "flux-drive.yaml").write_text(
            yaml.dump(cache), encoding="utf-8"
        )

        report = generate(tmp_path, mode="force", dry_run=True)
        assert report["status"] == "ok"
        assert not (tmp_path / ".claude" / "agents").exists()

    def test_orphan_detection(self, tmp_path):
        """Agents for removed domains are reported as orphaned."""
        cache_dir = tmp_path / ".claude"
        cache_dir.mkdir()
        cache = {"domains": [{"profile": "web-api", "confidence": 0.7}]}
        (cache_dir / "flux-drive.yaml").write_text(
            yaml.dump(cache), encoding="utf-8"
        )
        agents_dir = cache_dir / "agents"
        agents_dir.mkdir()
        (agents_dir / "fd-simulation-kernel.md").write_text(
            "---\ngenerated_by: flux-gen\ndomain: game-simulation\nflux_gen_version: 3\n---\n"
        )

        report = generate(tmp_path, mode="skip-existing")
        orphans = [a for a in report["agents"] if a.get("action") == "orphaned"]
        assert len(orphans) == 1
        assert orphans[0]["domain"] == "game-simulation"
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/mk/projects/Demarch/interverse/interflux && uv run --directory tests pytest tests/structural/test_generate_agents.py -v`
Expected: Most PASS (implementation already in Task 1), verify all pass.

**Step 3: Fix any test failures**

If any test fails, adjust the implementation in `generate-agents.py` to match the expected behavior.

**Step 4: Run full test suite**

Run: `cd /home/mk/projects/Demarch/interverse/interflux && uv run --directory tests pytest tests/structural/ -v`
Expected: All existing tests still pass + new tests pass

**Step 5: Commit**

```bash
git add tests/structural/test_generate_agents.py
git commit -m "test: add generation modes + rendering tests for generate-agents.py"
```

---

### Task 3: LLM-Based Domain Detection — Update SKILL.md Steps 1.0.1-1.0.3

**Files:**
- Modify: `interverse/interflux/skills/flux-drive/SKILL.md` (Steps 1.0.1-1.0.3)
- Modify: `interverse/interflux/skills/flux-drive/SKILL-compact.md` (matching sections)

**Step 1: Read the current Steps 1.0.1-1.0.3 in SKILL.md**

Read `interverse/interflux/skills/flux-drive/SKILL.md` lines 69-128 (Steps 1.0.1, 1.0.2, 1.0.3).

**Step 2: Replace Step 1.0.1 with LLM-based detection**

Replace the detection block in SKILL.md Step 1.0.1 with:

```markdown
### Step 1.0.1: Classify Project Domain

Detect the project's domain(s) for agent selection and domain-specific review criteria injection. Results are cached.

**Cache check:** Look for `{PROJECT_ROOT}/.claude/flux-drive.yaml`. If it exists and contains `domains:` with at least one entry, skip detection and use cached results. If the file also contains `override: true`, never re-detect — the user has manually set their domains.

**Detection** (when no cache, cache is stale, or `source: heuristic` in cache):

Launch a Haiku subagent to classify the project:

1. Read these files (skip any that don't exist):
   - `{PROJECT_ROOT}/README.md` (or README.rst, README.txt, README)
   - The primary build file (first found: `go.mod`, `Cargo.toml`, `package.json`, `pyproject.toml`, `CMakeLists.txt`, `Makefile`)
   - 2-3 key source files from the main source directory (pick files that reveal purpose, not utility)

2. Dispatch a Haiku subagent (Task tool, `model: haiku`) with this prompt:

   ```
   Classify this project into one or more of these domains based on its actual purpose.
   Return ONLY a JSON object, no other text.

   Available domains:
   - game-simulation (game engines, simulations, ECS, storytelling)
   - ml-pipeline (ML training, inference, experiment tracking)
   - web-api (REST/GraphQL/gRPC services, web backends)
   - cli-tool (command-line tools, terminal utilities)
   - mobile-app (iOS/Android/cross-platform mobile apps)
   - embedded-systems (firmware, RTOS, hardware drivers)
   - library-sdk (reusable libraries, SDKs, packages)
   - data-pipeline (ETL, data warehousing, stream processing)
   - claude-code-plugin (Claude Code plugins, skills, hooks)
   - tui-app (terminal user interfaces, ncurses/bubbletea apps)
   - desktop-tauri (desktop apps via Tauri/Electron/Wails)

   Project files:
   <include file contents here>

   Respond with:
   {"domains": [{"name": "<domain>", "confidence": <0.0-1.0>, "reasoning": "<1 sentence>"}]}

   Rules:
   - Only include domains with confidence >= 0.3
   - A project can match multiple domains (e.g., a game server is both game-simulation and web-api)
   - Set the highest-confidence domain as primary
   - If no domain matches above 0.3, return {"domains": []}
   ```

3. Parse the JSON response. Write to cache:
   ```bash
   # The cache is written by the host (flux-drive), not the subagent
   ```
   Cache format (write to `{PROJECT_ROOT}/.claude/flux-drive.yaml`):
   ```yaml
   cache_version: 2
   source: llm
   detected_at: '2026-02-22T12:00:00+00:00'
   content_hash: 'sha256:<hash of files read by LLM>'
   domains:
     - name: game-simulation
       confidence: 0.85
       reasoning: "Godot project with ECS architecture and storytelling system"
       primary: true
     - name: cli-tool
       confidence: 0.4
       reasoning: "Has CLI entry point for development tools"
   ```

**Heuristic fallback** (when Haiku call fails — timeout, API error, or unparseable response):

Run the legacy heuristic detector:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/detect-domains.py {PROJECT_ROOT} --json
```
- Exit 0: use output, mark `source: heuristic` in cache
- Exit 1: no domains detected, proceed with core agents only
- Exit 2: script error, proceed with core agents only

Log: `"Domain detection: LLM unavailable, using heuristic fallback. Results may be less accurate."`

**Performance budget:** Detection should complete in <5 seconds (Haiku is fast). Cache check is <10ms.
```

**Step 3: Replace Step 1.0.2 with content-hash staleness**

Replace the staleness check with:

```markdown
### Step 1.0.2: Check Staleness

Check if cached domain detection is outdated by comparing content hashes of the files the LLM read.

1. Read `content_hash` from `{PROJECT_ROOT}/.claude/flux-drive.yaml`
2. If no `content_hash` field (old cache format or heuristic source): cache is stale, proceed to Step 1.0.3
3. Re-hash the same files (README + build file + key source files)
4. If hashes match: cache is fresh, proceed to Step 1.1
5. If hashes differ: cache is stale, proceed to Step 1.0.3
```

**Step 4: Simplify Step 1.0.3**

Replace re-detect step with:

```markdown
### Step 1.0.3: Re-detect

When staleness is detected or no cache exists:

1. Read previous domains from cache (if any) for comparison
2. Run LLM detection (Step 1.0.1 detection flow)
3. Compare new vs previous:
   - Unchanged → proceed to Step 1.0.4
   - Changed → log: `"Domain shift: [old] → [new]"`. Proceed to Step 1.0.4
```

**Step 5: Update SKILL-compact.md to match**

Update the corresponding sections in SKILL-compact.md (lines 26-36) to reflect the LLM detection flow. Keep it compact — the compact version should reference the Haiku subagent approach but not repeat the full prompt.

```markdown
### Step 1.0.1: Domain Detection

**Cache check:** `{PROJECT_ROOT}/.claude/flux-drive.yaml` — if exists with `domains:` and `content_hash:` matches current files, use cached.

**Detection:** Launch Haiku subagent (Task tool, model: haiku) with README + build file + 2-3 source files. Returns `{domains: [{name, confidence, reasoning}]}`. Cache result with `source: llm` and content hash.

**Fallback:** If Haiku fails: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/detect-domains.py {PROJECT_ROOT} --json`. Mark `source: heuristic`.

**Staleness:** Compare content_hash in cache vs current file hashes. No hash → stale. Mismatch → stale. Match → fresh.
```

**Step 6: Commit**

```bash
git add skills/flux-drive/SKILL.md skills/flux-drive/SKILL-compact.md
git commit -m "feat: replace heuristic domain detection with LLM-based classification"
```

---

### Task 4: Update SKILL.md Step 1.0.4 to Invoke `generate-agents.py`

**Files:**
- Modify: `interverse/interflux/skills/flux-drive/SKILL.md` (Step 1.0.4)
- Modify: `interverse/interflux/skills/flux-drive/SKILL-compact.md` (Step 1.0.4)

**Step 1: Read current Step 1.0.4**

Read `interverse/interflux/skills/flux-drive/SKILL.md` lines 129-165.

**Step 2: Replace inline generation with script invocation**

Replace the entire Step 1.0.4 content with:

```markdown
### Step 1.0.4: Agent Generation

Auto-generate project-specific agents when domains are detected. Invokes the shared `generate-agents.py` script.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py {PROJECT_ROOT} --mode=regenerate-stale --json
```

**Exit codes:**
- **0**: Agents generated or all up-to-date. Parse JSON report from stdout.
- **1**: No domains in cache. Skip generation, proceed to Step 1.1 with core agents only.
- **2**: Script error. Log warning, proceed with core agents only.

**Interpret the JSON report:**

```json
{
  "status": "ok",
  "agents": [
    {"name": "fd-simulation-kernel", "domain": "game-simulation", "action": "created"},
    {"name": "fd-game-systems", "domain": "game-simulation", "action": "skipped", "reason": "up-to-date (v4)"},
    {"name": "fd-old-agent", "domain": "removed-domain", "action": "orphaned", "reason": "domain 'removed-domain' no longer detected"}
  ]
}
```

**Actions to report:**
- `created`: New agent generated. Log: `"Generated: {name} ({domain})"`
- `skipped`: Agent exists and is current. Silent.
- `regenerated`: Stale agent updated. Log: `"Regenerated: {name} ({reason})"`
- `orphaned`: Agent's domain no longer detected. Log: `"Orphaned: {name} — {reason}. Delete manually if unwanted."`
- `failed`: Profile missing or parse error. Log as warning.

**Summary line:**
```
Domain agents: N exist, M generated, K orphaned
```
```

**Step 3: Update SKILL-compact.md Step 1.0.4**

```markdown
### Step 1.0.4: Agent Generation

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py {PROJECT_ROOT} --mode=regenerate-stale --json
```
Exit 0: parse JSON (created/skipped/regenerated/orphaned). Exit 1: no domains. Exit 2: error. Report orphans, don't delete.
```

**Step 4: Commit**

```bash
git add skills/flux-drive/SKILL.md skills/flux-drive/SKILL-compact.md
git commit -m "feat: flux-drive Step 1.0.4 invokes generate-agents.py"
```

---

### Task 5: Update `flux-gen.md` Command to Use Shared Script

**Files:**
- Modify: `interverse/interflux/commands/flux-gen.md`

**Step 1: Read current flux-gen.md**

Read full file at `interverse/interflux/commands/flux-gen.md`.

**Step 2: Replace Steps 1-6 with new flow**

The new flux-gen.md should:
1. **Step 1 (Domain Detection):** Use the same LLM-based detection as flux-drive (Haiku subagent with fallback). Read cache first, re-detect if stale. Manual domain override via argument still works.
2. **Step 2 (Agent Specs Preview):** Run `generate-agents.py --dry-run --json` to show what would be generated.
3. **Step 3 (Confirm):** AskUserQuestion with three options:
   - "Generate N new agents (skip M existing)" → `--mode=skip-existing`
   - "Regenerate all (overwrite existing)" → `--mode=force`
   - "Cancel"
4. **Step 4 (Generate):** Run `generate-agents.py` with selected mode.
5. **Step 5 (Report):** Display summary from JSON output.

Keep the same frontmatter and argument-hint. Keep the Notes section at the bottom.

**Step 3: Commit**

```bash
git add commands/flux-gen.md
git commit -m "feat: flux-gen delegates generation to generate-agents.py"
```

---

### Task 6: Integration Test — End-to-End Generation

**Files:**
- Modify: `interverse/interflux/tests/structural/test_generate_agents.py`

**Step 1: Write CLI integration test**

```python
class TestCLIIntegration:
    def test_cli_json_output(self, tmp_path):
        """CLI with --json outputs valid JSON report."""
        # Set up fake project with cache
        cache_dir = tmp_path / ".claude"
        cache_dir.mkdir()
        cache = {"cache_version": 2, "source": "llm",
                 "domains": [{"name": "game-simulation", "confidence": 0.8}]}
        (cache_dir / "flux-drive.yaml").write_text(
            yaml.dump(cache), encoding="utf-8"
        )

        result = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), str(tmp_path),
             "--mode=skip-existing", "--json"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        report = json.loads(result.stdout)
        assert report["status"] == "ok"
        created = [a for a in report["agents"] if a["action"] == "created"]
        assert len(created) >= 2  # game-simulation has 3 domain agents

    def test_cli_no_cache_exits_1(self, tmp_path):
        """CLI with no cache file exits with code 1."""
        result = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), str(tmp_path), "--json"],
            capture_output=True, text=True
        )
        assert result.returncode == 1

    def test_cli_dry_run_creates_no_files(self, tmp_path):
        """CLI with --dry-run reports but writes nothing."""
        cache_dir = tmp_path / ".claude"
        cache_dir.mkdir()
        cache = {"domains": [{"name": "web-api", "confidence": 0.7}]}
        (cache_dir / "flux-drive.yaml").write_text(
            yaml.dump(cache), encoding="utf-8"
        )

        result = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), str(tmp_path),
             "--mode=force", "--dry-run", "--json"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert not (tmp_path / ".claude" / "agents").exists()
```

**Step 2: Run tests**

Run: `cd /home/mk/projects/Demarch/interverse/interflux && uv run --directory tests pytest tests/structural/test_generate_agents.py -v`
Expected: All pass

**Step 3: Run full structural test suite**

Run: `cd /home/mk/projects/Demarch/interverse/interflux && uv run --directory tests pytest tests/structural/ -v`
Expected: All pass (existing detect-domains tests still work, new tests pass)

**Step 4: Commit**

```bash
git add tests/structural/test_generate_agents.py
git commit -m "test: add CLI integration tests for generate-agents.py"
```

---

### Task 7: Simplify `detect-domains.py` to Fallback-Only

**Files:**
- Modify: `interverse/interflux/scripts/detect-domains.py`
- Modify: `interverse/interflux/tests/structural/test_detect_domains.py`

**Step 1: Read the full detect-domains.py to identify what to keep**

The heuristic fallback only needs: `load_index`, `gather_*`, `score_domain`, `detect`, `write_cache`, `read_cache`, and CLI entry point. The staleness detection (tiers 1-3), structural hashing, and elaborate cache management can be removed — staleness is now handled by content hashing in the SKILL.md flow.

**Step 2: Remove staleness detection code**

Remove these functions and their tests:
- `compute_structural_hash`
- `_check_stale_tier1`, `_check_stale_tier2`, `_check_stale_tier3`
- `check_stale`
- `STRUCTURAL_FILES`, `STRUCTURAL_EXTENSIONS` constants
- `--check-stale` CLI flag

Keep the `--json` and `--no-cache` flags. Add a comment at the top noting this is the heuristic fallback for when LLM detection is unavailable.

**Step 3: Update tests**

Remove test classes that test staleness:
- `TestCheckStale` (and any tier-specific tests)
- `TestStructuralHash`

Keep: `TestLoadIndex`, `TestScoring`, `TestGather*`, `TestDetect`, `TestCLI` (minus staleness CLI tests).

**Step 4: Run tests**

Run: `cd /home/mk/projects/Demarch/interverse/interflux && uv run --directory tests pytest tests/structural/test_detect_domains.py -v`
Expected: Remaining tests all pass

**Step 5: Commit**

```bash
git add scripts/detect-domains.py tests/structural/test_detect_domains.py
git commit -m "refactor: simplify detect-domains.py to heuristic fallback only"
```
