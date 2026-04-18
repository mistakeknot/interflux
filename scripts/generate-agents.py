#!/usr/bin/env python3
"""Generate project-specific review agents from LLM-designed task specs.

Reads agent specs as JSON from a file (typically LLM-generated via flux-gen
prompt mode) and renders them through a template pipeline into
.claude/agents/fd-*.md agent files.

Exit codes:
    0  Agents generated (or nothing to do)
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sanitize_untrusted import sanitize, sanitize_list  # noqa: E402
from spec_types import (  # noqa: E402
    _normalize_bullet_list,
    _unwrap_spec_list,
    validate_agent_spec,
)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# Set by --verbose flag in main()
_verbose = False


def _log(msg: str) -> None:
    """Print diagnostic message to stderr when --verbose is set."""
    if _verbose:
        print(f"[generate-agents] {msg}", file=sys.stderr)

# Current generation version — bump when template format changes
# v5: severity calibration (severity_examples field + escalation instruction)
# v6: extended frontmatter (tier, domains, use_count, source_spec)
FLUX_GEN_VERSION = 6

# Core agents that should NOT be generated from specs
CORE_AGENTS = frozenset({
    "fd-architecture",
    "fd-safety",
    "fd-correctness",
    "fd-quality",
    "fd-performance",
    "fd-user-product",
    "fd-game-design",
})


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _short_title(bullet: str) -> str:
    """Derive a short section title from a review area bullet.

    Takes the first clause (up to a clause-level delimiter) and strips
    leading imperative verbs. Preserves hyphens (compound words), periods
    in numbers/namespaces, and truncates at word boundaries.
    """
    if not bullet:
        return ""
    # Split on clause-level delimiters only:
    #   ", " (comma-space), " — " (em-dash), " - " (spaced hyphen)
    # Do NOT split on bare hyphens, periods, or "and"/"so" conjunctions
    short = re.split(r", | — | - ", bullet, maxsplit=1)[0].strip()
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
    # Truncate at word boundary if too long
    if len(short) > 80:
        truncated = short[:80]
        # Find last space to avoid mid-word cut
        last_space = truncated.rfind(" ")
        if last_space > 40:  # don't truncate too aggressively
            short = truncated[:last_space]
        else:
            short = truncated
    return short


def _render_severity_calibration(
    severity_examples: list[dict[str, str]] | None,
    focus: str,
) -> str:
    """Render the ## Severity Calibration section.

    If severity_examples are provided (from LLM spec), render them as structured
    scenarios. Otherwise, generate a domain-generic fallback from the focus area.
    """
    lines = ["## Severity Calibration", ""]

    if severity_examples:
        for ex in severity_examples:
            sev = ex.get("severity", "P0")
            scenario = ex.get("scenario", "")
            condition = ex.get("condition", "")
            lines.append(f"- **{sev}**: {scenario}")
            if condition:
                lines.append(f"  - When: {condition}")
    else:
        # Domain-generic fallback derived from focus
        focus_lower = focus.lower().rstrip(".")
        lines.append(
            f"- **P0**: {focus_lower} issue that causes data loss, corruption, or blocks other work"
        )
        lines.append(
            f"- **P1**: {focus_lower} issue required to pass the current quality gate"
        )
        lines.append(
            "- **P2/P3**: Quality degradation, maintenance burden, or style preferences"
        )

    lines.append("")
    lines.append(
        "When in doubt: describe the failure scenario. "
        "If it wakes someone at 3 AM, it is P0/P1. "
        "If it degrades quality over weeks, it is P2."
    )
    lines.append("")
    return "\n".join(lines)


def _infer_domains_from_spec(spec: dict[str, Any]) -> list[str]:
    """Infer domain tags from spec fields."""
    domains = set()
    name = spec.get("name", "").lower()
    focus = (spec.get("focus") or "").lower()
    source_domain = (spec.get("source_domain") or "").lower()

    # Check name segments
    segments = name.split("-")[1:]  # drop "fd"
    domain_map = {
        "routing": "routing", "navigation": "navigation", "wayfinding": "navigation",
        "security": "security", "safety": "safety", "auth": "security",
        "trust": "security", "performance": "performance", "architecture": "architecture",
        "migration": "migration", "schema": "data-modeling", "ontology": "data-modeling",
        "pipeline": "pipeline", "queue": "pipeline", "dispatch": "orchestration",
        "orchestration": "orchestration", "scheduler": "orchestration",
        "governance": "governance", "authority": "governance",
        "budget": "economics", "cost": "economics",
        "test": "testing", "benchmark": "testing",
        "observability": "observability", "monitor": "observability",
        "agent": "agent-systems", "inference": "ml-inference",
        "cache": "infrastructure", "storage": "infrastructure",
    }
    for seg in segments:
        if seg in domain_map:
            domains.add(domain_map[seg])

    # Check for esoteric source domains
    esoteric_signals = [
        "wayfinding", "calligraphy", "gamelan", "qanat", "heraldic",
        "byzantine", "benedictine", "akkadian", "polynesian", "andean",
        "subak", "liturgical", "sword",
    ]
    for sig in esoteric_signals:
        if sig in name or sig in source_domain:
            domains.add("esoteric-lens")
            break

    return sorted(domains) if domains else ["uncategorized"]


def render_agent(spec: dict[str, Any], source_spec_file: str | None = None) -> str:
    """Render an LLM-generated agent spec into the full agent markdown file.

    Returns the complete file content including YAML frontmatter.

    Untrusted LLM-authored fields (persona, decision_lens, review_areas,
    task_context, anti_overlap, success_hints) are sanitized before embedding.
    See scripts/sanitize_untrusted.py and blueprint §3 B3.
    """
    name = spec["name"]
    focus = spec.get("focus", "")
    task_context = sanitize(spec.get("task_context", ""), max_len=1000)

    persona = sanitize(spec.get("persona"), max_len=500)
    if not persona:
        persona = (
            f"You are a specialist reviewer focused on {focus.lower().rstrip('.')} "
            f"— methodical, specific, and grounded in project reality."
        )

    decision_lens = sanitize(spec.get("decision_lens"), max_len=500)
    if not decision_lens:
        decision_lens = (
            f"Prioritize findings by real-world impact. "
            f"Flag issues that would cause failures before style concerns."
        )

    # Version gating: only emit v5 when severity_examples is present
    severity_examples = spec.get("severity_examples")
    has_severity = bool(severity_examples and isinstance(severity_examples, list))
    effective_version = FLUX_GEN_VERSION if has_severity else 4

    now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    domains = _infer_domains_from_spec(spec)

    review_sections = ""
    review_areas = sanitize_list(_normalize_bullet_list(spec.get("review_areas")), max_item_len=200)
    for idx, area in enumerate(review_areas, start=1):
        title = _short_title(area)
        review_sections += f"\n### {idx}. {title}\n\n"
        review_sections += f"- {area}\n"

    success_bullets = (
        "- Ties every finding to a specific file, function, and line number — never a vague \"consider X\"\n"
        "- Provides a concrete failure scenario for each P0/P1 finding — what breaks, under what conditions, and who is affected\n"
        "- Recommends the smallest viable fix, not an architecture overhaul — one diff hunk, not a rewrite\n"
        "- Frames uncertain findings as questions: \"Does this handle X?\" not \"This doesn't handle X\"\n"
    )
    for hint in sanitize_list(_normalize_bullet_list(spec.get("success_hints")), max_item_len=200):
        success_bullets += f"- {hint}\n"

    # Build anti-overlap list from other agents in the same prompt batch
    anti_overlap_items = sanitize_list(_normalize_bullet_list(spec.get("anti_overlap")), max_item_len=200)
    if anti_overlap_items:
        bullets = "\n".join(f"- {item}" for item in anti_overlap_items)
        anti_overlap_section = (
            "## What NOT to Flag\n\n"
            f"{bullets}\n"
            "- Only flag the above if they are deeply entangled with your specialist focus "
            "and another agent would miss the nuance\n\n"
        )
    else:
        anti_overlap_section = ""

    # Build severity calibration section
    severity_section = _render_severity_calibration(severity_examples, focus)

    task_section = f"## Task Context\n\n{task_context}\n\n" if task_context else ""

    # Escalation instruction appended to decision lens
    escalation = (
        " If you find an issue matching a P0/P1 scenario in Severity Calibration, "
        "label it P0 or P1 — do not downgrade to appear less alarming."
    )

    domains_yaml = json.dumps(domains)
    source_line = f"\nsource_spec: '{source_spec_file}'" if source_spec_file else ""

    content = f"""---
model: sonnet
generated_by: flux-gen-prompt
generated_at: '{now_utc}'
flux_gen_version: {effective_version}
tier: generated
domains: {domains_yaml}
use_count: 0{source_line}
---
# {name} — Task-Specific Reviewer

> Generated by `/flux-gen` from a task prompt.
> Customize this file for your specific needs.

{persona}

## First Step (MANDATORY)

Read all project documentation before reviewing:
1. `CLAUDE.md` and `AGENTS.md` in the project root
2. Any files specified in the task context below

Ground every finding in the project's actual patterns and conventions.
Reuse the project's terminology, not generic terms.

{task_section}## Review Approach
{review_sections}
{severity_section}
{anti_overlap_section}## Success Criteria

A good review from this agent:
{success_bullets}
## Decision Lens

{decision_lens}{escalation}

## Prioritization

- P0: Issues that block other work, cause data loss or corruption — drop everything
- P1: Issues required to exit the current quality gate
- P2: Issues that degrade quality or create maintenance burden
- P3: Improvements and polish — suggest but don't block on these
- For each P0/P1 finding, describe the concrete failure scenario: what breaks, under what conditions, and who is affected
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
    Only includes agents that have ``generated_by: flux-gen`` or ``flux-gen-prompt`` in frontmatter.
    """
    try:
        import yaml  # noqa: F401
    except ImportError:
        raise RuntimeError("pyyaml is required – install with: pip install pyyaml")

    result: dict[str, dict[str, Any]] = {}
    if not agents_dir.is_dir():
        return result

    for f in sorted(agents_dir.glob("fd-*.md")):
        frontmatter = _parse_frontmatter(f)
        if frontmatter and frontmatter.get("generated_by") in ("flux-gen", "flux-gen-prompt"):
            name = f.stem  # e.g. 'fd-simulation-kernel'
            result[name] = frontmatter

    return result


def _parse_frontmatter(path: Path) -> dict[str, Any] | None:
    """Parse YAML frontmatter from a markdown file."""
    try:
        import yaml
    except ImportError:
        return None

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return None

    end = text.find("\n---", 3)
    if end == -1:
        return None

    try:
        data = yaml.safe_load(text[3:end])
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
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

def generate_from_specs(
    project: Path,
    specs_path: Path,
    mode: str = "skip-existing",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate agents from an LLM-produced specs JSON file.

    The specs file should contain a JSON array of objects, each with:
        name (str): Agent name, must start with 'fd-'
        focus (str): One-line focus description
        persona (str, optional): Agent persona
        decision_lens (str, optional): Decision prioritization guidance
        review_areas (list[str]): Bullet points for review approach
        success_hints (list[str], optional): Additional success criteria
        task_context (str, optional): Context about the task/research question
        anti_overlap (list[str], optional): What NOT to flag (other agents cover it)

    Returns a report dict with keys: status, generated, skipped, errors.
    """
    agents_dir = project / ".claude" / "agents"

    report: dict[str, Any] = {
        "status": "ok",
        "specs_count": 0,
        "generated": [],
        "skipped": [],
        "reused": [],  # existing proven/used agents that cover the domain
        "errors": [],
    }

    try:
        raw = specs_path.read_text(encoding="utf-8")
        specs = json.loads(raw)
    except Exception as exc:
        report["status"] = "error"
        report["errors"].append(f"Failed to read specs: {exc}")
        return report

    # Unwrap common LLM wrapper patterns: {"agents": [...]} or {"specs": [...]}
    # Shared helper with flux-agent.py — see scripts/spec_types.py.
    specs, unwrap_note = _unwrap_spec_list(specs)
    if unwrap_note:
        _log(unwrap_note)

    if not specs:
        report["status"] = "error"
        report["errors"].append(
            "Specs file must contain a JSON array (or an object with a single array value)"
        )
        return report

    report["specs_count"] = len(specs)
    _log(f"parsed {len(specs)} spec(s), agents_dir={agents_dir}")

    existing = check_existing_agents(agents_dir)
    _log(f"found {len(existing)} existing flux-gen agent(s)")

    # Build domain→proven/used agent index for overlap detection
    _domain_agents: dict[str, list[str]] = {}
    for ename, efm in existing.items():
        etier = efm.get("tier", "")
        if etier in ("proven", "used"):
            for d in efm.get("domains", []):
                _domain_agents.setdefault(d, []).append(ename)
    _log(f"domain index: {len(_domain_agents)} domains with proven/used agents")

    specs_file_name = specs_path.name

    # Strict name pattern: fd- prefix followed by lowercase alphanumerics joined by hyphens.
    # startswith("fd-") alone allows path-traversal (fd-../../etc/cron.d/evil) because the
    # name is used as a filesystem path downstream.
    _NAME_PATTERN = re.compile(r"^fd-[a-z0-9]+(?:-[a-z0-9]+)*$")

    for spec in specs:
        # Structural validation before rendering. anti_overlap v0.2.58 incident
        # (116 corrupted files) was an LLM-JSON → render_agent boundary gap;
        # validate_agent_spec is the single enforcement point.
        is_valid, validation_errors, spec = validate_agent_spec(spec, name_pattern=_NAME_PATTERN.pattern)
        if not is_valid:
            bad_name = spec.get("name") or "<unnamed>"
            for err in validation_errors:
                report["errors"].append(f"Skipping '{bad_name}': {err}")
            continue

        name = spec["name"]

        if name in CORE_AGENTS:
            report["errors"].append(f"Skipping '{name}': conflicts with core agent")
            continue

        if name in existing:
            if mode == "skip-existing":
                report["skipped"].append(name)
                continue
            elif mode == "regenerate-stale":
                # YAML loads numeric frontmatter as int, but hand-edited files
                # may have quoted strings. Coerce to int before comparing.
                raw_version = existing[name].get("flux_gen_version", 0)
                try:
                    existing_version = int(raw_version)
                except (TypeError, ValueError):
                    existing_version = 0
                if existing_version >= FLUX_GEN_VERSION:
                    report["skipped"].append(name)
                    continue

        # Domain overlap check: if a proven/used agent covers the same domains,
        # log it as "reused" but still generate (the triage will prefer the
        # proven agent via scoring). Only skip if exact name match (above).
        spec_domains = _infer_domains_from_spec(spec)
        overlapping = set()
        for d in spec_domains:
            if d != "uncategorized":
                overlapping.update(_domain_agents.get(d, []))
        if overlapping:
            _log(f"{name}: domain overlap with proven/used agents: {overlapping}")
            report["reused"].append({
                "new": name,
                "overlapping": sorted(overlapping),
                "domains": spec_domains,
            })

        content = render_agent(spec, source_spec_file=specs_file_name)
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
        description="Generate project-specific review agents from LLM-designed specs.",
    )
    parser.add_argument("project_root", type=Path, help="Path to the project root")
    parser.add_argument(
        "--from-specs",
        type=Path,
        required=True,
        metavar="SPECS_JSON",
        help="Generate from LLM-produced specs JSON file",
    )
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
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print diagnostic trace to stderr",
    )
    args = parser.parse_args()

    global _verbose
    _verbose = args.verbose

    project = args.project_root.resolve()
    _log(f"project_root={project}, specs={args.from_specs}, mode={args.mode}, json={args.json_output}")

    if not project.is_dir():
        print(f"Error: {project} is not a directory", file=sys.stderr)
        return 2

    specs_path = args.from_specs.resolve()
    if not specs_path.exists():
        print(f"Error: specs file not found: {specs_path}", file=sys.stderr)
        return 2

    _log(f"specs_path={specs_path} ({specs_path.stat().st_size} bytes)")

    try:
        report = generate_from_specs(project, specs_path, mode=args.mode, dry_run=args.dry_run)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if report.get("status") == "error":
        if args.json_output:
            print(json.dumps(report, indent=2))
        else:
            for err in report.get("errors", []):
                print(f"Error: {err}", file=sys.stderr)
        return 2

    gen = report["generated"]
    skip = report["skipped"]
    reused = report.get("reused", [])
    errs = report.get("errors", [])

    # Detect silent failure: specs had entries but nothing was generated or skipped
    specs_count = report.get("specs_count", 0)
    if not gen and not skip and specs_count > 0:
        report["status"] = "warning"
        report["errors"].append(
            f"Specs file had {specs_count} entries but produced 0 agents and 0 skips. "
            f"Check that spec objects have 'name' fields starting with 'fd-'."
        )
        _log(f"silent failure: {specs_count} specs produced nothing")

    if args.json_output:
        print(json.dumps(report, indent=2))
    else:
        action = "Would generate" if args.dry_run else "Generated"
        print(f"{action} {len(gen)} agent(s), skipped {len(skip)}.")
        if gen:
            print(f"  Generated: {', '.join(gen)}")
        if skip:
            print(f"  Skipped: {', '.join(skip)}")
        if reused:
            print(f"  Domain overlap: {len(reused)} new agents overlap with proven/used agents")
            for r in reused[:5]:
                print(f"    {r['new']} ↔ {', '.join(r['overlapping'][:3])}")
        for err in errs:
            print(f"  Warning: {err}", file=sys.stderr)
        if not gen and not skip:
            print("  Warning: no agents generated or skipped — check specs file content", file=sys.stderr)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        raise SystemExit(2)
