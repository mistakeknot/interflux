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

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# Set by --verbose flag in main()
_verbose = False


def _log(msg: str) -> None:
    """Print diagnostic message to stderr when --verbose is set."""
    if _verbose:
        print(f"[generate-agents] {msg}", file=sys.stderr)

# Current generation version — bump when template format changes
# v5: severity calibration (severity_examples field + escalation instruction)
FLUX_GEN_VERSION = 5

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


def render_agent(spec: dict[str, Any]) -> str:
    """Render an LLM-generated agent spec into the full agent markdown file.

    Returns the complete file content including YAML frontmatter.
    """
    name = spec["name"]
    focus = spec.get("focus", "")
    task_context = spec.get("task_context", "")

    persona = spec.get("persona")
    if not persona:
        persona = (
            f"You are a specialist reviewer focused on {focus.lower().rstrip('.')} "
            f"— methodical, specific, and grounded in project reality."
        )

    decision_lens = spec.get("decision_lens")
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

    review_sections = ""
    for idx, area in enumerate(spec.get("review_areas", []), start=1):
        title = _short_title(area)
        review_sections += f"\n### {idx}. {title}\n\n"
        review_sections += f"- {area}\n"

    success_bullets = (
        "- Ties every finding to a specific file, function, and line number — never a vague \"consider X\"\n"
        "- Provides a concrete failure scenario for each P0/P1 finding — what breaks, under what conditions, and who is affected\n"
        "- Recommends the smallest viable fix, not an architecture overhaul — one diff hunk, not a rewrite\n"
        "- Frames uncertain findings as questions: \"Does this handle X?\" not \"This doesn't handle X\"\n"
    )
    for hint in spec.get("success_hints", []):
        success_bullets += f"- {hint}\n"

    # Build anti-overlap list from other agents in the same prompt batch
    anti_overlap = spec.get("anti_overlap", [])
    anti_overlap_section = ""
    if anti_overlap:
        anti_overlap_section = "## What NOT to Flag\n\n"
        for item in anti_overlap:
            anti_overlap_section += f"- {item}\n"
        anti_overlap_section += "- Only flag the above if they are deeply entangled with your specialist focus and another agent would miss the nuance\n\n"

    # Build severity calibration section
    severity_section = _render_severity_calibration(severity_examples, focus)

    task_section = ""
    if task_context:
        task_section = f"""## Task Context

{task_context}

"""

    # Escalation instruction appended to decision lens
    escalation = (
        " If you find an issue matching a P0/P1 scenario in Severity Calibration, "
        "label it P0 or P1 — do not downgrade to appear less alarming."
    )

    content = f"""---
model: sonnet
generated_by: flux-gen-prompt
generated_at: '{now_utc}'
flux_gen_version: {effective_version}
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
        "generated": [],
        "skipped": [],
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
    if isinstance(specs, dict) and not isinstance(specs, list):
        candidates = [v for v in specs.values() if isinstance(v, list)]
        if len(candidates) == 1:
            _log(f"unwrapped JSON object with key(s) {list(specs.keys())} → {len(candidates[0])} specs")
            specs = candidates[0]
        else:
            _log(f"specs is dict with keys {list(specs.keys())}, not a list — will error")

    if not isinstance(specs, list):
        report["status"] = "error"
        report["errors"].append(
            "Specs file must contain a JSON array (or an object with a single array value)"
        )
        return report

    _log(f"parsed {len(specs)} spec(s), agents_dir={agents_dir}")

    existing = check_existing_agents(agents_dir)
    _log(f"found {len(existing)} existing flux-gen agent(s)")

    for spec in specs:
        name = spec.get("name", "")
        if not name.startswith("fd-"):
            report["errors"].append(f"Skipping '{name}': name must start with 'fd-'")
            continue

        if name in CORE_AGENTS:
            report["errors"].append(f"Skipping '{name}': conflicts with core agent")
            continue

        if name in existing:
            if mode == "skip-existing":
                report["skipped"].append(name)
                continue
            elif mode == "regenerate-stale":
                existing_version = existing[name].get("flux_gen_version", 0)
                if isinstance(existing_version, int) and existing_version >= FLUX_GEN_VERSION:
                    report["skipped"].append(name)
                    continue

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

    if args.json_output:
        print(json.dumps(report, indent=2))
    else:
        gen = report["generated"]
        skip = report["skipped"]
        action = "Would generate" if args.dry_run else "Generated"
        print(f"{action} {len(gen)} agent(s), skipped {len(skip)}.")
        if gen:
            print(f"  Generated: {', '.join(gen)}")
        if skip:
            print(f"  Skipped: {', '.join(skip)}")
        for err in report.get("errors", []):
            print(f"  Error: {err}", file=sys.stderr)

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
