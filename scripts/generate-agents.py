#!/usr/bin/env python3
"""Generate project-specific review agents from detected domain profiles.

Reads cached domain detection results from .claude/flux-drive.yaml, parses
domain profile markdown files from config/flux-drive/domains/{domain}.md,
and generates .claude/agents/fd-*.md agent files deterministically.

Exit codes:
    0  Agents generated (or nothing to do)
    1  No domains detected (no cache)
    2  Fatal error
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
    print("Error: pyyaml is required – install with: pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DOMAINS_DIR = PLUGIN_ROOT / "config" / "flux-drive" / "domains"

# Current generation version — bump when template format changes
FLUX_GEN_VERSION = 4

# Core agents that should NOT be generated from domain profiles
CORE_AGENTS = frozenset({
    "fd-architecture",
    "fd-safety",
    "fd-correctness",
    "fd-quality",
    "fd-performance",
    "fd-user-product",
    "fd-game-design",
})

# Domain-specific doc types for the First Step section
DOMAIN_DOC_TYPES: dict[str, str] = {
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


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _domain_display_name(domain: str) -> str:
    """Convert domain slug to human-readable display name.

    Examples: 'game-simulation' -> 'Game Simulation', 'ml-pipeline' -> 'ML Pipeline'
    """
    return domain.replace("-", " ").title()


def parse_agent_specs(profile_path: Path, domain: str) -> list[dict[str, Any]]:
    """Extract agent specifications from a domain profile markdown file.

    Parses the ``## Agent Specifications`` section. Each ``### fd-*``
    subsection contains Focus, Persona, Decision lens, Key review areas,
    and optionally Success criteria hints.

    Returns a list of spec dicts, each with keys:
        name, domain, focus, persona, decision_lens,
        review_areas (list[str]), success_hints (list[str])
    """
    text = profile_path.read_text(encoding="utf-8")

    # Find the Agent Specifications section
    agent_section_match = re.search(
        r"^## Agent Specifications\s*\n(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not agent_section_match:
        return []

    section_text = agent_section_match.group(1)

    # Split into individual agent subsections by ### fd-*
    agent_blocks = re.split(r"^### (fd-[\w-]+)\s*$", section_text, flags=re.MULTILINE)
    # agent_blocks[0] is the preamble text before the first ### fd-*
    # Then alternating: name, content, name, content, ...

    specs: list[dict[str, Any]] = []
    i = 1
    while i < len(agent_blocks) - 1:
        name = agent_blocks[i].strip()
        content = agent_blocks[i + 1]
        i += 2

        # Skip core agents
        if name in CORE_AGENTS:
            continue

        spec = _parse_single_agent(content, name, domain)
        specs.append(spec)

    return specs


def _parse_single_agent(content: str, name: str, domain: str) -> dict[str, Any]:
    """Parse a single agent subsection content into a spec dict."""
    # Extract Focus line
    focus_match = re.search(r"^Focus:\s*(.+)$", content, re.MULTILINE)
    focus = focus_match.group(1).strip() if focus_match else ""

    # Extract Persona line
    persona_match = re.search(r"^Persona:\s*(.+)$", content, re.MULTILINE)
    persona = persona_match.group(1).strip() if persona_match else None

    # Extract Decision lens line
    lens_match = re.search(r"^Decision lens:\s*(.+)$", content, re.MULTILINE)
    decision_lens = lens_match.group(1).strip() if lens_match else None

    # Extract Key review areas (bullet list)
    review_areas: list[str] = []
    review_match = re.search(
        r"^Key review areas:\s*\n((?:- .+\n?)+)",
        content,
        re.MULTILINE,
    )
    if review_match:
        for line in review_match.group(1).strip().splitlines():
            line = line.strip()
            if line.startswith("- "):
                review_areas.append(line[2:].strip())

    # Extract Success criteria hints (optional bullet list)
    success_hints: list[str] = []
    hints_match = re.search(
        r"^Success criteria hints:\s*\n((?:- .+\n?)+)",
        content,
        re.MULTILINE,
    )
    if hints_match:
        for line in hints_match.group(1).strip().splitlines():
            line = line.strip()
            if line.startswith("- "):
                success_hints.append(line[2:].strip())

    return {
        "name": name,
        "domain": domain,
        "focus": focus,
        "persona": persona,
        "decision_lens": decision_lens,
        "review_areas": review_areas,
        "success_hints": success_hints,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _short_title(bullet: str) -> str:
    """Derive a short section title from a review area bullet.

    Takes the first clause (up to the first comma, dash, period, or 'and')
    and strips leading verbs like Check/Verify/Validate/Confirm/Ensure.
    """
    # Take up to first major punctuation or conjunction
    short = re.split(r"[,\.\-—]| and | so ", bullet, maxsplit=1)[0].strip()
    # Strip leading imperative verb
    short = re.sub(
        r"^(Check that|Check|Verify that|Verify|Validate|Confirm|Ensure that|Ensure)\s+",
        "",
        short,
        flags=re.IGNORECASE,
    )
    # Capitalize first letter
    if short:
        short = short[0].upper() + short[1:]
    # Truncate if too long
    if len(short) > 60:
        short = short[:57] + "..."
    return short


def render_agent(spec: dict[str, Any]) -> str:
    """Render a parsed agent spec dict into the full agent markdown file.

    Returns the complete file content including YAML frontmatter.
    """
    domain = spec["domain"]
    name = spec["name"]
    focus = spec.get("focus", "")
    domain_display = _domain_display_name(domain)

    # Persona — use provided or fallback
    persona = spec.get("persona")
    if not persona:
        persona = (
            f"You are a {domain_display.lower()} {focus.lower().rstrip('.')} "
            f"specialist — methodical, specific, and grounded in project reality."
        )

    # Decision lens — use provided or fallback
    decision_lens = spec.get("decision_lens")
    if not decision_lens:
        decision_lens = (
            f"Prioritize findings by real-world impact on {domain_display.lower()} projects. "
            f"Flag issues that would cause failures in production before style concerns."
        )

    # Domain-specific doc types
    doc_types = DOMAIN_DOC_TYPES.get(domain, "Project-specific documentation")

    # Timestamp — deterministic UTC
    now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    # Build review approach sections
    review_sections = ""
    for idx, area in enumerate(spec.get("review_areas", []), start=1):
        title = _short_title(area)
        review_sections += f"\n### {idx}. {title}\n\n"
        review_sections += f"- {area}\n"

    # Build success criteria
    success_bullets = (
        "- Ties every finding to a specific file, function, and line number — never a vague \"consider X\"\n"
        "- Provides a concrete failure scenario for each P0/P1 finding — what breaks, under what conditions, and who is affected\n"
        "- Recommends the smallest viable fix, not an architecture overhaul — one diff hunk, not a rewrite\n"
        "- Distinguishes domain-specific expertise from generic code quality (defer the latter to core agents listed in \"What NOT to Flag\")\n"
        "- Frames uncertain findings as questions: \"Does this handle X?\" not \"This doesn't handle X\"\n"
    )
    for hint in spec.get("success_hints", []):
        success_bullets += f"- {hint}\n"

    # Assemble full file
    content = f"""---
generated_by: flux-gen
domain: {domain}
generated_at: '{now_utc}'
flux_gen_version: {FLUX_GEN_VERSION}
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
- Apply best practices for {domain} projects
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

A good {domain} review:
{success_bullets}
## Decision Lens

{decision_lens}

When two fixes compete for attention, choose the one with higher real-world impact on {domain} concerns.

## Prioritization

- P0/P1: Issues that would cause failures, data loss, or broken functionality in production
- P2: Issues that degrade quality or create maintenance burden
- P3: Improvements and polish — suggest but don't block on these
- Always tie findings to specific files, functions, and line numbers
- Frame uncertain findings as questions, not assertions
"""
    return content


# ---------------------------------------------------------------------------
# Existing agent checking
# ---------------------------------------------------------------------------

def check_existing_agents(agents_dir: Path) -> dict[str, dict[str, Any]]:
    """Read existing fd-*.md files and parse YAML frontmatter.

    Returns dict of agent name (e.g. 'fd-simulation-kernel') -> frontmatter dict.
    Only includes agents that have ``generated_by: flux-gen`` in frontmatter.
    """
    result: dict[str, dict[str, Any]] = {}
    if not agents_dir.is_dir():
        return result

    for f in sorted(agents_dir.glob("fd-*.md")):
        frontmatter = _parse_frontmatter(f)
        if frontmatter and frontmatter.get("generated_by") == "flux-gen":
            name = f.stem  # e.g. 'fd-simulation-kernel'
            result[name] = frontmatter

    return result


def _parse_frontmatter(path: Path) -> dict[str, Any] | None:
    """Parse YAML frontmatter from a markdown file.

    Returns the parsed dict, or None if no valid frontmatter found.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    if not text.startswith("---"):
        return None

    end = text.find("---", 3)
    if end == -1:
        return None

    try:
        return yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None


# ---------------------------------------------------------------------------
# Atomic file writes
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, content: str) -> None:
    """Write content to a file atomically using tempfile + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")

    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    closed = False
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.rename(tmp_path, str(path))
    except Exception:
        if not closed:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------

def generate(
    project: Path,
    mode: str = "skip-existing",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate domain-specific agent files.

    Args:
        project: Path to the project root.
        mode: One of 'skip-existing', 'regenerate-stale', 'force'.
        dry_run: If True, report what would happen but don't write files.

    Returns:
        Structured report dict with keys:
            status: 'ok' | 'no_domains'
            generated: list of agent names that were generated
            skipped: list of agent names that were skipped (already exist)
            orphaned: list of agent names whose domain is no longer detected
            errors: list of error message strings
    """
    cache_path = project / ".claude" / "flux-drive.yaml"
    agents_dir = project / ".claude" / "agents"

    report: dict[str, Any] = {
        "status": "ok",
        "generated": [],
        "skipped": [],
        "orphaned": [],
        "errors": [],
    }

    # Read domain cache
    if not cache_path.exists():
        report["status"] = "no_domains"
        return report

    try:
        cache_data = yaml.safe_load(cache_path.read_text(encoding="utf-8"))
    except Exception as exc:
        report["status"] = "no_domains"
        report["errors"].append(f"Failed to read cache: {exc}")
        return report

    if not isinstance(cache_data, dict) or not cache_data.get("domains"):
        report["status"] = "no_domains"
        return report

    domains = cache_data["domains"]
    detected_domain_names = {d["name"] for d in domains if isinstance(d, dict) and "name" in d}

    if not detected_domain_names:
        report["status"] = "no_domains"
        return report

    # Check existing agents
    existing = check_existing_agents(agents_dir)

    # Detect orphaned agents (generated agents whose domain is no longer detected)
    for agent_name, fm in existing.items():
        agent_domain = fm.get("domain", "")
        if agent_domain and agent_domain not in detected_domain_names:
            report["orphaned"].append(agent_name)

    # Collect all specs from detected domains
    all_specs: list[dict[str, Any]] = []
    for domain_entry in domains:
        domain_name = domain_entry.get("name", "")
        if not domain_name:
            continue
        profile_path = DOMAINS_DIR / f"{domain_name}.md"
        if not profile_path.exists():
            report["errors"].append(f"Domain profile not found: {profile_path}")
            continue

        specs = parse_agent_specs(profile_path, domain_name)
        all_specs.extend(specs)

    # Generate agents based on mode
    for spec in all_specs:
        name = spec["name"]

        if name in existing:
            if mode == "skip-existing":
                report["skipped"].append(name)
                continue
            elif mode == "regenerate-stale":
                existing_version = existing[name].get("flux_gen_version", 0)
                if isinstance(existing_version, int) and existing_version >= FLUX_GEN_VERSION:
                    report["skipped"].append(name)
                    continue
                # else: version is old, regenerate
            # mode == "force": always regenerate

        # Render and write
        content = render_agent(spec)
        if not dry_run:
            target = agents_dir / f"{name}.md"
            _atomic_write(target, content)
        report["generated"].append(name)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate project-specific review agents from detected domain profiles.",
    )
    parser.add_argument("project_root", type=Path, help="Path to the project root")
    parser.add_argument(
        "--mode",
        choices=["skip-existing", "regenerate-stale", "force"],
        default="skip-existing",
        help="Generation mode (default: skip-existing)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output JSON report",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen without writing files",
    )
    args = parser.parse_args()

    project = args.project_root.resolve()
    if not project.is_dir():
        print(f"Error: {project} is not a directory", file=sys.stderr)
        return 2

    try:
        report = generate(project, mode=args.mode, dry_run=args.dry_run)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if report["status"] == "no_domains":
        if args.json_output:
            print(json.dumps(report, indent=2))
        else:
            for err in report.get("errors", []):
                print(f"Error: {err}", file=sys.stderr)
            print("No domains detected. Run detect-domains.py first.", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps(report, indent=2))
    else:
        gen = report["generated"]
        skip = report["skipped"]
        orph = report["orphaned"]
        action = "Would generate" if args.dry_run else "Generated"
        print(f"{action} {len(gen)} agent(s), skipped {len(skip)}, orphaned {len(orph)}.")
        if gen:
            print(f"  Generated: {', '.join(gen)}")
        if skip:
            print(f"  Skipped: {', '.join(skip)}")
        if orph:
            print(f"  Orphaned: {', '.join(orph)}")
        for err in report.get("errors", []):
            print(f"  Error: {err}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)
