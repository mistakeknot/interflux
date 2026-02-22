# Flux-Gen as Flux-Drive Pre-Check + LLM-Based Domain Detection

**Bead:** iv-uaf8
**Date:** 2026-02-22
**Status:** Brainstorm complete

## What We're Building

Two coupled changes to interflux's domain detection and agent generation pipeline:

1. **Replace heuristic domain detection with LLM-based classification.** The current `detect-domains.py` uses weighted signal scoring (directory names, file extensions, framework refs, keywords) which is inaccurate — generic signals like `models/`, `api/`, `src/`, `*.go` match everything, producing false positives. Replace with a Haiku subagent that reads README + 2-3 key files and classifies the project's actual purpose.

2. **Replace inline agent generation with a deterministic `generate-agents.py` script.** flux-drive Step 1.0.4 reimplements flux-gen's template in SKILL.md markdown. Both describe the same agent file format but drift. Extract to a single Python script that both invoke.

### Current State

- `detect-domains.py` (712 lines) — heuristic scoring on 11 domain profiles from `index.yaml`. Signals are structural (dir/file/framework/keyword) with hardcoded weights (dir:0.3, file:0.2, framework:0.3, keyword:0.2). Cached to `.claude/flux-drive.yaml` with structural-hash staleness checks.
- flux-drive Step 1.0.4 — inline generation logic in SKILL.md that duplicates flux-gen.md's template.
- `/flux-gen` command — interactive agent generator, also reads domain profiles, also applies the same template with LLM interpretation.

**Problem with heuristic detection:** Signals encode *technology choices*, not *project purpose*. A Go CLI with a `models/` dir and `api/` handler falsely triggers ml-pipeline and web-api. The weighted scoring can't distinguish "this directory exists" from "this project is about this domain." An LLM reading the README resolves this instantly.

### Target State

- `detect-domains.py` → replaced by a Haiku/fast-model subagent call that:
  - Reads README + build files + 2-3 key source files (~3-5K tokens)
  - Returns structured JSON: `{domains: [{name, confidence, reasoning}]}`
  - Caches to `.claude/flux-drive.yaml` with content hash for staleness
  - Falls back to heuristic if LLM unavailable (offline, API error)
- `generate-agents.py` (new) — deterministic script that reads cached domains + domain profiles → writes `.claude/agents/fd-*.md`
- flux-gen.md → thin orchestrator: interactive UX + calls generate-agents.py
- flux-drive SKILL.md Step 1.0.x → calls detection (subagent or cached), then generate-agents.py

## Why This Approach

1. **Accurate detection** — LLM understands project purpose from context, not just file patterns. "This is a TUI monitoring tool" vs. "this has a `ui/` directory."
2. **Deterministic generation** — same domain → same agent files, every time. The Composer (C3) needs predictable agent definitions.
3. **Single source of truth** — generation template in Python, not duplicated across two markdown files.
4. **Cheap** — Haiku classification costs ~$0.001/call, runs once per project state change, result is cached.
5. **Graceful degradation** — heuristic stays as offline fallback. If the LLM call fails, fall back to the old scoring. Not great, but better than nothing.

## Key Decisions

### Detection (replacing detect-domains.py)

1. **Haiku subagent for classification** — use Claude Haiku (or equivalent fast model) via a Task tool call with `model: haiku`. The prompt reads the project's README, build file(s), and 2-3 key source files, then classifies into the 11 known domains with confidence scores and reasoning.

2. **Cache with content-hash staleness** — cache the LLM classification result in `.claude/flux-drive.yaml` (same location as current cache). Staleness is determined by hashing the files the LLM read (README, build files). If hashes match, use cache. If changed, re-classify.

3. **Heuristic as fallback** — keep the scoring logic (simplified) as an offline/error fallback. If the LLM call fails (network error, API error), run the heuristic and mark the result as `source: heuristic` in the cache so it gets re-evaluated next time the LLM is available.

4. **Domain list stays fixed** — the 11 domains in index.yaml are still the classification targets. The LLM picks from this list (closed-set classification), not open-ended. This keeps agent generation deterministic — we only have profiles for these 11 domains.

5. **Detection runs from SKILL.md instructions, not a Python script** — since the detection is now an LLM call, it's naturally expressed as SKILL.md instructions ("launch a Haiku subagent with this prompt"). The Python script (`detect-domains.py`) is retained as the heuristic fallback only. The cache read/write/staleness logic can stay in Python or move to simple shell commands.

### Generation (new generate-agents.py)

6. **Separate scripts** — `generate-agents.py` takes cached domain classification as input. Does not do detection.

7. **Three generation modes** (via `--mode` flag):
   - `skip-existing` — only generate missing agents (flux-drive default for first-time projects)
   - `regenerate-stale` — regenerate agents with older `flux_gen_version`, skip current (flux-drive default when agents exist)
   - `force` — regenerate all agents (flux-gen "overwrite" option)

8. **No LLM in generation** — domain profile review bullets included verbatim. Deterministic template expansion. The LLM's role is classification (detection), not content generation.

9. **Interactive UX stays in flux-gen.md** — the command asks the user before overwriting. It delegates actual file writing to the script.

10. **flux-drive Step 1.0.4 becomes a script invocation:**
    ```bash
    python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py {PROJECT_ROOT} --mode=regenerate-stale --json
    ```

## Integration Points

**Detection (LLM-based):**
- **Input:** Project files (README, build files, key source files) — read by Haiku subagent
- **Input:** Domain list from `config/flux-drive/domains/index.yaml` (names only — the prompt includes the list)
- **Output:** `.claude/flux-drive.yaml` (cached classification: domains, confidences, reasoning, content hash)
- **Fallback input:** Same index.yaml + project structure (heuristic scoring)

**Generation (deterministic):**
- **Input:** `.claude/flux-drive.yaml` (cached domains)
- **Input:** `config/flux-drive/domains/{domain}.md` (domain profiles with Agent Specifications)
- **Output:** `.claude/agents/fd-{name}.md` (generated agent files)
- **Output:** JSON to stdout (generation report: created/skipped/stale/failed per agent)

## Exit Codes (generate-agents.py)

- **0** — agents generated (or all up-to-date)
- **1** — no domains in cache (nothing to generate)
- **2** — script error (missing profiles, parse failure)

## Open Questions

1. **Should detect-domains.py be kept as-is (712 lines) for fallback, or simplified?** The current script has elaborate staleness checking, structural hashing, and cache management that's mostly superseded by the LLM approach. Could strip it to ~100 lines of pure heuristic scoring. **Lean:** simplify — the staleness logic moves to the SKILL.md cache-check flow.

2. **Should the Haiku prompt include the full index.yaml domain definitions, or just domain names?** Full definitions (~450 lines) provide better classification context but cost more tokens. Just names (~11 lines) is cheaper but may miss edge cases. **Lean:** include the `profile` name + `signals.frameworks` list for each domain (~30 lines) — enough for the LLM to understand what each domain means without the full signal definitions.

## Scope Boundaries

**In scope:**
- LLM-based domain detection (Haiku subagent call in SKILL.md)
- `scripts/generate-agents.py` — shared deterministic generation script
- Update `commands/flux-gen.md` to use generate-agents.py
- Update `skills/flux-drive/SKILL.md` Steps 1.0.1-1.0.4 for new detection + generation flow
- Cache format update in `.claude/flux-drive.yaml` (add `source: llm|heuristic`, content hash)
- Heuristic fallback (simplified detect-domains.py or inline)

**Out of scope:**
- New domain profiles
- Changes to agent scoring or triage (Step 1.2) — scoring still uses the same domain data
- Changes to domain profile content (`config/flux-drive/domains/*.md`)
- Composer (C3) integration — that's a separate track
