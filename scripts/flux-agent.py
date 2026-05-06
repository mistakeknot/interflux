#!/usr/bin/env python3
"""Flux agent lifecycle manager — index, backfill, stats, prune, promote.

Manages the quality-tiered agent registry in .claude/agents/. Agents carry
their own metadata in YAML frontmatter (tier, domains, use_count, etc.) and
this script builds a cached index (.index.yaml) for fast triage lookup.

Subcommands:
    index     Scan agent frontmatter, rebuild .index.yaml
    backfill  Add extended frontmatter to existing agents (one-time migration)
    stats     Show tier distribution, domain coverage, staleness
    prune     Identify stale stubs for deletion (--apply to delete)
    promote   Manually set an agent's tier
    record    Record usage for agents after a flux-drive review

Exit codes:
    0  Success
    1  Partial success (some agents failed)
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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _debug(msg: str, *args: Any) -> None:
    """Print a debug line to stderr when INTERFLUX_DEBUG is set.

    Used by exception handlers that intentionally swallow errors so the silence
    is observable when investigating. Adds no overhead in normal runs (env var
    is checked once per call). See scripts/README.md § Python error handling.
    """
    if os.environ.get("INTERFLUX_DEBUG"):
        try:
            sys.stderr.write((msg % args) + "\n")
        except (TypeError, ValueError):
            sys.stderr.write(f"{msg} {args}\n")
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spec_types import _normalize_domains, _unwrap_spec_list  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIERS = ("stub", "generated", "used", "proven")
TIER_ORDER = {t: i for i, t in enumerate(TIERS)}

# Agents at or below this line count with zero usage are classified as stubs
STUB_LINE_THRESHOLD = 80

# Minimum usage + line count for auto-promotion to "proven"
PROVEN_MIN_USES = 3
PROVEN_MIN_LINES = 150

# Days without use before demotion consideration
STALE_DAYS = 90

# Domain extraction: keywords in agent names that map to domains
# Used as fallback when domains aren't explicitly set in frontmatter
DOMAIN_KEYWORDS = {
    "routing": "routing",
    "navigation": "navigation",
    "wayfinding": "navigation",
    "security": "security",
    "safety": "safety",
    "auth": "security",
    "trust": "security",
    "performance": "performance",
    "latency": "performance",
    "throughput": "performance",
    "architecture": "architecture",
    "migration": "migration",
    "schema": "data-modeling",
    "ontology": "data-modeling",
    "graph": "data-modeling",
    "pipeline": "pipeline",
    "queue": "pipeline",
    "dispatch": "orchestration",
    "orchestration": "orchestration",
    "scheduler": "orchestration",
    "governance": "governance",
    "authority": "governance",
    "budget": "economics",
    "cost": "economics",
    "pricing": "economics",
    "test": "testing",
    "benchmark": "testing",
    "observability": "observability",
    "monitor": "observability",
    "telemetry": "observability",
    "ui": "user-interface",
    "ux": "user-interface",
    "tui": "user-interface",
    "agent": "agent-systems",
    "swarm": "agent-systems",
    "loop": "agent-systems",
    "inference": "ml-inference",
    "model": "ml-inference",
    "cache": "infrastructure",
    "storage": "infrastructure",
    "sync": "infrastructure",
}


# ---------------------------------------------------------------------------
# Frontmatter parsing / writing
# ---------------------------------------------------------------------------

def _parse_frontmatter(path: Path) -> dict[str, Any] | None:
    """Parse YAML frontmatter from a markdown file."""
    try:
        import yaml
    except ImportError:
        raise RuntimeError("pyyaml required: pip install pyyaml")

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
        return data if isinstance(data, dict) else None
    except Exception as exc:
        _debug("flux-agent: frontmatter parse failed: %s", exc)
        return None


def _update_frontmatter(path: Path, updates: dict[str, Any]) -> bool:
    """Update YAML frontmatter fields in-place, preserving body content."""
    try:
        import yaml
    except ImportError:
        raise RuntimeError("pyyaml required: pip install pyyaml")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    stripped = text.lstrip("\ufeff")
    if not stripped.startswith("---"):
        return False

    end = stripped.find("\n---", 3)
    if end == -1:
        return False

    try:
        data = yaml.safe_load(stripped[3:end])
        if not isinstance(data, dict):
            return False
    except Exception as exc:
        _debug("flux-agent: frontmatter update parse failed for %s: %s", path, exc)
        return False

    data.update(updates)
    new_fm = yaml.dump(data, default_flow_style=False, sort_keys=False).rstrip("\n")
    body = stripped[end + 4:]  # skip \n---
    new_content = f"---\n{new_fm}\n---{body}"

    _atomic_write(path, new_content)
    return True


def _classify_initial_tier(use_count: int, line_count: int) -> str:
    """Classify tier for an agent that has none set in frontmatter.

    Used by _scan_agents (auto-classify during read) and cmd_backfill
    (one-time migration). Note: cmd_record uses a promote-only variant
    that never demotes to "stub", so it does not call this helper.
    """
    if use_count >= PROVEN_MIN_USES and line_count >= PROVEN_MIN_LINES:
        return "proven"
    if use_count >= 1:
        return "used"
    if line_count <= STUB_LINE_THRESHOLD:
        return "stub"
    return "generated"


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically using tempfile + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    closed = False
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.rename(tmp, str(path))
    except Exception as exc:
        _debug("flux-agent: atomic write failed for %s: %s", path, exc)
        if not closed:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Domain inference
# ---------------------------------------------------------------------------

def _infer_domains(name: str, content: str = "") -> list[str]:
    """Infer domain tags from agent name parts.

    Only matches against hyphen-delimited segments of the agent name
    (e.g. fd-airline-yield-management-routing → ["routing", "economics"]).
    Content scanning is intentionally skipped — too many false positives
    from generic words in agent prose.
    """
    domains = set()
    # Split on hyphens to get name segments (skip "fd" prefix)
    segments = name.lower().split("-")[1:]  # drop "fd"
    name_text = " ".join(segments)

    for keyword, domain in DOMAIN_KEYWORDS.items():
        # Match whole segments or multi-word phrases in the joined name
        if keyword in segments or keyword in name_text:
            domains.add(domain)

    # Esoteric lens: non-technical source domains
    esoteric_signals = [
        "wayfinding", "calligraphy", "gamelan", "qanat", "heraldic",
        "byzantine", "benedictine", "akkadian", "polynesian", "andean",
        "subak", "sword", "perfume", "weaving", "pottery", "brewing",
        "liturgical", "typikon", "iconographic", "extispicy", "hepatoscopy",
    ]
    for sig in esoteric_signals:
        if sig in segments:
            domains.add("esoteric-lens")
            break

    return sorted(domains) if domains else ["uncategorized"]


# ---------------------------------------------------------------------------
# Agent scanning
# ---------------------------------------------------------------------------

def _scan_agents(agents_dir: Path) -> list[dict[str, Any]]:
    """Scan all fd-*.md files and return structured metadata."""
    agents = []
    if not agents_dir.is_dir():
        return agents

    for f in sorted(agents_dir.glob("fd-*.md")):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue

        line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        fm = _parse_frontmatter(f)
        if fm is None:
            fm = {}

        name = f.stem
        # YAML may load numeric counts as str (e.g. quoted "5"); coerce.
        try:
            use_count = int(fm.get("use_count") or 0)
        except (TypeError, ValueError):
            use_count = 0
        tier = fm.get("tier")
        domains = fm.get("domains")

        # Auto-classify tier if not set
        if tier is None:
            tier = _classify_initial_tier(use_count, line_count)

        # Infer domains if not set
        if not domains:
            domains = _infer_domains(name, text)

        # LLMs sometimes emit "security, auth" as a single comma-joined string;
        # wrapping as [domains] produced a single "security, auth" bucket.
        # _normalize_domains splits on [,;] whether input is list or string.
        domains = _normalize_domains(domains) if not isinstance(domains, list) or any(
            isinstance(d, str) and ("," in d or ";" in d) for d in domains
        ) else domains

        agents.append({
            "name": name,
            "file": str(f),
            "lines": line_count,
            "tier": tier,
            "domains": domains,
            "use_count": use_count,
            "last_used": fm.get("last_used"),
            "last_scored": fm.get("last_scored"),
            "generated_by": fm.get("generated_by"),
            "generated_at": fm.get("generated_at"),
            "flux_gen_version": fm.get("flux_gen_version"),
            "source_spec": fm.get("source_spec"),
            "model": fm.get("model"),
        })

    return agents


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_index(args: argparse.Namespace) -> int:
    """Build .index.yaml from agent frontmatter."""
    try:
        import yaml
    except ImportError:
        print("Error: pyyaml required", file=sys.stderr)
        return 2

    agents_dir = args.project_root / ".claude" / "agents"
    agents = _scan_agents(agents_dir)

    if not agents:
        print("No agents found.", file=sys.stderr)
        return 1

    # Build tier counts
    tier_counts = Counter(a["tier"] for a in agents)

    # Build domain index
    domain_index: dict[str, list[str]] = defaultdict(list)
    for a in agents:
        for d in a["domains"]:
            domain_index[d].append(a["name"])

    # Build proven/used quick-lookup lists
    proven = [
        {
            "name": a["name"],
            "domains": a["domains"],
            "lines": a["lines"],
            "use_count": a["use_count"],
            "last_used": a["last_used"],
        }
        for a in agents
        if a["tier"] == "proven"
    ]
    proven.sort(key=lambda x: x.get("use_count", 0), reverse=True)

    used = [
        {
            "name": a["name"],
            "domains": a["domains"],
            "lines": a["lines"],
            "use_count": a["use_count"],
        }
        for a in agents
        if a["tier"] == "used"
    ]

    index = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_agents": len(agents),
        "by_tier": dict(tier_counts),
        "domains": {k: sorted(v) for k, v in sorted(domain_index.items())},
        "proven": proven,
        "used": used,
    }

    index_path = agents_dir / ".index.yaml"
    content = yaml.dump(index, default_flow_style=False, sort_keys=False)
    _atomic_write(index_path, f"# Auto-generated by flux-agent index\n# Rebuild: flux-agent index --rebuild\n{content}")

    if args.json:
        print(json.dumps({"status": "ok", "agents": len(agents), "by_tier": dict(tier_counts)}, indent=2))
    else:
        print(f"Index rebuilt: {len(agents)} agents")
        for tier in TIERS:
            print(f"  {tier}: {tier_counts.get(tier, 0)}")
        print(f"  domains: {len(domain_index)}")
        print(f"  written: {index_path}")

    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    """Add extended frontmatter to existing agents that lack it."""
    agents_dir = args.project_root / ".claude" / "agents"
    agents = _scan_agents(agents_dir)

    # Cross-reference with synthesis docs for usage data
    usage_counts = _count_usage_from_synthesis(args.project_root)

    updated = 0
    skipped = 0
    errors = 0

    for a in agents:
        path = Path(a["file"])
        fm = _parse_frontmatter(path)
        if fm is None:
            errors += 1
            continue

        # Skip if already has extended frontmatter
        if "tier" in fm and "domains" in fm and "use_count" in fm:
            skipped += 1
            continue

        # Determine usage from synthesis docs
        use_count = usage_counts.get(a["name"], 0)
        line_count = a["lines"]
        tier = _classify_initial_tier(use_count, line_count)

        # Infer domains
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        domains = _infer_domains(a["name"], text)

        updates: dict[str, Any] = {
            "tier": tier,
            "domains": domains,
            "use_count": use_count,
        }

        # Add source_spec if we can find it
        spec_source = _find_source_spec(a["name"], args.project_root)
        if spec_source:
            updates["source_spec"] = spec_source

        if args.dry_run:
            print(f"  would update: {a['name']} → tier={tier}, domains={domains}, use_count={use_count}")
            updated += 1
            continue

        if _update_frontmatter(path, updates):
            updated += 1
        else:
            errors += 1

    if args.json:
        print(json.dumps({"updated": updated, "skipped": skipped, "errors": errors}))
    else:
        action = "Would update" if args.dry_run else "Updated"
        print(f"{action} {updated} agents, skipped {skipped} (already backfilled), {errors} errors")

    return 0 if errors == 0 else 1


def cmd_stats(args: argparse.Namespace) -> int:
    """Show agent statistics."""
    agents_dir = args.project_root / ".claude" / "agents"
    agents = _scan_agents(agents_dir)

    if not agents:
        print("No agents found.")
        return 1

    tier_counts = Counter(a["tier"] for a in agents)
    domain_counts = Counter()
    for a in agents:
        for d in a["domains"]:
            domain_counts[d] += 1

    # Line count stats
    lines = [a["lines"] for a in agents]
    lines.sort()

    # Staleness: agents not used in STALE_DAYS+
    today = dt.date.today()
    stale = []
    for a in agents:
        lu = a.get("last_used")
        if lu and isinstance(lu, str):
            try:
                last = dt.date.fromisoformat(lu[:10])
                if (today - last).days > STALE_DAYS:
                    stale.append(a["name"])
            except ValueError:
                pass

    if args.json:
        print(json.dumps({
            "total": len(agents),
            "by_tier": dict(tier_counts),
            "top_domains": dict(domain_counts.most_common(15)),
            "line_stats": {
                "min": lines[0], "max": lines[-1],
                "median": lines[len(lines) // 2],
                "p90": lines[int(len(lines) * 0.9)],
            },
            "stale_count": len(stale),
        }, indent=2))
    else:
        print(f"Agent Registry: {len(agents)} agents\n")
        print("Tier Distribution:")
        for tier in TIERS:
            count = tier_counts.get(tier, 0)
            pct = count / len(agents) * 100
            bar = "█" * int(pct / 2)
            print(f"  {tier:12s} {count:4d} ({pct:4.1f}%) {bar}")

        print(f"\nTop Domains (of {len(domain_counts)}):")
        for domain, count in domain_counts.most_common(10):
            print(f"  {domain:25s} {count:4d} agents")

        print(f"\nLine Counts:")
        print(f"  min={lines[0]}  median={lines[len(lines)//2]}  p90={lines[int(len(lines)*0.9)]}  max={lines[-1]}")

        if stale:
            print(f"\nStale ({len(stale)} agents not used in {STALE_DAYS}+ days)")

    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    """Identify stale stub agents for deletion."""
    agents_dir = args.project_root / ".claude" / "agents"
    agents = _scan_agents(agents_dir)

    today = dt.date.today()
    candidates = []

    for a in agents:
        # Prune criteria: stub tier + never used + older than stale_days
        if a["tier"] != "stub" or a["use_count"] > 0:
            continue

        gen_at = a.get("generated_at")
        if gen_at and isinstance(gen_at, str):
            try:
                gen_date = dt.date.fromisoformat(gen_at[:10])
                age_days = (today - gen_date).days
                if age_days < (args.min_age or STALE_DAYS):
                    continue
            except ValueError:
                pass

        candidates.append(a)

    if not candidates:
        print("No prune candidates found.")
        return 0

    if args.json:
        print(json.dumps({
            "candidates": len(candidates),
            "names": [c["name"] for c in candidates],
            "applied": args.apply,
        }, indent=2))
    else:
        print(f"Prune candidates: {len(candidates)} stub agents (never used, >{args.min_age or STALE_DAYS}d old)\n")
        for c in candidates[:20]:
            print(f"  {c['name']:55s} {c['lines']:4d} lines  gen: {c.get('generated_at', '?')[:10]}")
        if len(candidates) > 20:
            print(f"  ... and {len(candidates) - 20} more")

    if args.apply:
        deleted = 0
        for c in candidates:
            try:
                Path(c["file"]).unlink()
                deleted += 1
            except OSError as e:
                print(f"  error deleting {c['name']}: {e}", file=sys.stderr)
        print(f"\nDeleted {deleted}/{len(candidates)} agents.")

    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """Manually set an agent's tier."""
    agents_dir = args.project_root / ".claude" / "agents"
    target = agents_dir / f"{args.agent}.md"

    if not target.exists():
        print(f"Agent not found: {args.agent}", file=sys.stderr)
        return 2

    tier = args.tier
    if tier not in TIERS:
        print(f"Invalid tier: {tier}. Must be one of: {', '.join(TIERS)}", file=sys.stderr)
        return 2

    if _update_frontmatter(target, {"tier": tier}):
        print(f"Promoted {args.agent} → {tier}")
        return 0
    else:
        print(f"Failed to update {args.agent}", file=sys.stderr)
        return 1


def cmd_record(args: argparse.Namespace) -> int:
    """Record usage for agents after a flux-drive review.

    Increments use_count, updates last_used, and auto-promotes tier.
    """
    agents_dir = args.project_root / ".claude" / "agents"
    today = dt.date.today().isoformat()
    updated = 0

    for name in args.agents:
        path = agents_dir / f"{name}.md"
        if not path.exists():
            print(f"  skip (not found): {name}", file=sys.stderr)
            continue

        fm = _parse_frontmatter(path)
        if fm is None:
            print(f"  skip (no frontmatter): {name}", file=sys.stderr)
            continue

        # Quoted-numeric frontmatter ("5") is common after hand edits; coerce.
        try:
            use_count = int(fm.get("use_count") or 0) + 1
        except (TypeError, ValueError):
            use_count = 1
        line_count = path.read_text(encoding="utf-8").count("\n")

        # Auto-promote tier
        current_tier = fm.get("tier", "generated")
        if use_count >= PROVEN_MIN_USES and line_count >= PROVEN_MIN_LINES:
            new_tier = "proven"
        elif use_count >= 1:
            new_tier = "used"
        else:
            new_tier = current_tier

        updates = {
            "use_count": use_count,
            "last_used": today,
            "tier": new_tier,
        }

        if _update_frontmatter(path, updates):
            promotion = f" (promoted: {current_tier} → {new_tier})" if new_tier != current_tier else ""
            print(f"  recorded: {name} use_count={use_count}{promotion}")
            updated += 1

    print(f"\n{updated}/{len(args.agents)} agents updated.")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_usage_from_synthesis(project: Path) -> dict[str, int]:
    """Count unique synthesis dirs each agent is referenced in.

    A single review mentioning an agent 5 times counts as 1 use —
    we count unique parent directory names, not raw mentions.
    """
    flux_dir = project / "docs" / "research" / "flux-drive"
    if not flux_dir.is_dir():
        return {}

    _agent_ref = re.compile(r"\bfd-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\b")
    dir_counts: dict[str, set[str]] = defaultdict(set)
    for md in flux_dir.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        parent = md.parent.name
        for match in _agent_ref.findall(text):
            dir_counts[match].add(parent)

    return {name: len(dirs) for name, dirs in dir_counts.items()}


def _find_source_spec(agent_name: str, project: Path) -> str | None:
    """Find which flux-gen spec file generated an agent."""
    specs_dir = project / ".claude" / "flux-gen-specs"
    if not specs_dir.is_dir():
        return None

    for spec_file in specs_dir.glob("*.json"):
        try:
            raw = json.loads(spec_file.read_text(encoding="utf-8"))
            # Shared unwrap: handles {"agents": [...]} and {"specs": [...]}.
            specs, _note = _unwrap_spec_list(raw)
            for s in specs:
                if isinstance(s, dict) and s.get("name") == agent_name:
                    return spec_file.name
        except Exception as exc:
            _debug("flux-agent: spec scan skipped %s: %s", spec_file, exc)
            continue

    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Flux agent lifecycle manager — index, backfill, stats, prune, promote.",
        prog="flux-agent",
    )
    parser.add_argument(
        "project_root", type=Path, nargs="?", default=Path("."),
        help="Project root (default: current directory)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # index
    p_index = sub.add_parser("index", help="Rebuild .index.yaml from agent frontmatter")
    p_index.add_argument("--json", action="store_true")

    # backfill
    p_back = sub.add_parser("backfill", help="Add extended frontmatter to existing agents")
    p_back.add_argument("--dry-run", action="store_true")
    p_back.add_argument("--json", action="store_true")

    # stats
    p_stats = sub.add_parser("stats", help="Show agent statistics")
    p_stats.add_argument("--json", action="store_true")

    # prune
    p_prune = sub.add_parser("prune", help="Identify stale stubs for deletion")
    p_prune.add_argument("--apply", action="store_true", help="Actually delete candidates")
    p_prune.add_argument("--min-age", type=int, help=f"Minimum age in days (default: {STALE_DAYS})")
    p_prune.add_argument("--json", action="store_true")

    # promote
    p_promote = sub.add_parser("promote", help="Manually set an agent's tier")
    p_promote.add_argument("agent", help="Agent name (e.g. fd-polynesian-wayfinding-star-path)")
    p_promote.add_argument("--tier", required=True, choices=TIERS)

    # record
    p_record = sub.add_parser("record", help="Record usage for agents after a review")
    p_record.add_argument("agents", nargs="+", help="Agent names that participated")

    args = parser.parse_args()
    args.project_root = args.project_root.resolve()

    if not args.project_root.is_dir():
        print(f"Error: {args.project_root} is not a directory", file=sys.stderr)
        return 2

    handlers = {
        "index": cmd_index,
        "backfill": cmd_backfill,
        "stats": cmd_stats,
        "prune": cmd_prune,
        "promote": cmd_promote,
        "record": cmd_record,
    }

    return handlers[args.command](args)


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
