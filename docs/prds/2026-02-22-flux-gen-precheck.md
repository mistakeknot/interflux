# PRD: LLM-Based Domain Detection + Deterministic Agent Generation

**Bead:** iv-uaf8

## Problem

Flux-drive's domain detection uses heuristic file/directory scanning that produces inaccurate results — generic signals like `models/`, `api/`, `src/` match everything, causing false positives. Agent generation logic is duplicated between flux-gen.md and flux-drive SKILL.md Step 1.0.4, causing drift and non-deterministic output.

## Solution

Replace heuristic domain detection with a cached Haiku subagent classification call. Extract agent generation into a shared deterministic Python script (`generate-agents.py`) invoked by both flux-gen and flux-drive.

## Features

### F1: LLM-Based Domain Detection
**What:** Replace `detect-domains.py` heuristic scoring with a Haiku subagent that reads project files and classifies into known domains.

**Acceptance criteria:**
- [ ] Haiku subagent reads README + build file + 2-3 key source files and returns `{domains: [{name, confidence, reasoning}]}`
- [ ] Classification is constrained to the 11 known domains from index.yaml (closed-set)
- [ ] Result is cached to `.claude/flux-drive.yaml` with a content hash of files read
- [ ] Cache includes `source: llm|heuristic` field to distinguish detection method
- [ ] Staleness check compares content hash — re-classifies only when source files change
- [ ] Heuristic fallback runs when LLM is unavailable (API error, timeout) — result marked `source: heuristic`
- [ ] Detection prompt includes domain names + framework lists (~30 lines) for classification context
- [ ] SKILL.md Steps 1.0.1-1.0.3 updated to use new detection flow

### F2: Deterministic Agent Generation Script
**What:** Python script (`scripts/generate-agents.py`) that reads cached domains + domain profiles and writes `.claude/agents/fd-*.md` files deterministically.

**Acceptance criteria:**
- [ ] Script reads `.claude/flux-drive.yaml` for domain list and `config/flux-drive/domains/{domain}.md` for agent specs
- [ ] Parses `## Agent Specifications` sections from domain profile markdown
- [ ] Generates agent files using the existing template format (YAML frontmatter + sections)
- [ ] Domain profile review bullets included verbatim (no LLM inference for sub-criteria)
- [ ] Three modes via `--mode` flag: `skip-existing`, `regenerate-stale`, `force`
- [ ] `regenerate-stale` checks `flux_gen_version` in frontmatter — regenerates older versions, skips current
- [ ] `--json` flag outputs structured report: created/skipped/stale/failed per agent
- [ ] `--dry-run` flag reports what would happen without writing files
- [ ] Exit codes: 0 (success), 1 (no domains), 2 (script error)
- [ ] Handles orphaned agent detection (domain removed) — reports but does not delete

### F3: Flux-Drive SKILL.md Integration
**What:** Update flux-drive Steps 1.0.1-1.0.4 to use the new LLM detection and `generate-agents.py`.

**Acceptance criteria:**
- [ ] Step 1.0.1 uses Haiku subagent call instead of `python3 detect-domains.py`
- [ ] Step 1.0.2 staleness check uses content hash from cache (not structural file hash)
- [ ] Step 1.0.3 re-detect triggers new Haiku call when stale
- [ ] Step 1.0.4 invokes `python3 generate-agents.py {PROJECT_ROOT} --mode=regenerate-stale --json`
- [ ] Orphan detection and domain-shift reporting interpret generate-agents.py JSON output
- [ ] Heuristic fallback path works when Haiku call fails
- [ ] SKILL-compact.md updated to match SKILL.md changes

### F4: Flux-Gen Command Integration
**What:** Update `/flux-gen` command to delegate generation to `generate-agents.py` while keeping interactive UX.

**Acceptance criteria:**
- [ ] flux-gen.md invokes `generate-agents.py` instead of inline template logic
- [ ] Interactive overwrite prompt (AskUserQuestion) still works — maps to `--mode` flag
- [ ] "Generate N new agents (skip M existing)" → `--mode=skip-existing`
- [ ] "Regenerate all (overwrite existing)" → `--mode=force`
- [ ] Domain detection uses the same Haiku subagent flow as flux-drive
- [ ] Manual domain override (`/flux-gen game-simulation`) still works — bypasses detection
- [ ] Report format matches current flux-gen output

## Non-goals

- New domain profiles — the 11 existing domains stay as-is
- Changes to agent scoring or triage (Step 1.2) — scoring still consumes the same domain data
- Open-ended domain discovery (LLM suggesting domains outside the 11 known ones)
- Removing detect-domains.py entirely — it stays as the heuristic fallback
- Composer (C3) integration — separate track

## Dependencies

- Claude Haiku model access via Task tool (available in Claude Code)
- Existing domain profiles in `config/flux-drive/domains/*.md`
- Existing cache format in `.claude/flux-drive.yaml` (extended, not replaced)
- PyYAML (already a dependency of detect-domains.py)

## Open Questions

1. **Simplified heuristic fallback:** Should we keep the full 712-line `detect-domains.py` as fallback, or strip it to ~100 lines of pure scoring? Lean: simplify — the elaborate staleness/caching logic is superseded by the LLM approach.
2. **Domain profile parsing:** `generate-agents.py` needs to extract `## Agent Specifications` from markdown. Regex on well-structured markdown is reliable enough, or should we add a YAML sidecar? Lean: regex — profiles are stable.
