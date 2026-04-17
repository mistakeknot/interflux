---
name: flux-drive
description: Use when reviewing documents or codebases with multi-agent analysis, or researching topics with multi-agent research — triages relevant agents from roster, launches only what matters in background mode
---

# Flux Drive — Intelligent Multi-Agent Review & Research

<!-- compact: SKILL-compact.md — if it exists in this directory, load it instead of following the multi-file instructions below. The compact version contains the same triage algorithm, scoring formula, and agent roster in a single file. For launch protocol and synthesis details, read phases/launch.md and phases/synthesize.md as directed by the compact file. -->

You are executing the flux-drive skill. This skill operates in two modes:

- **review** (default): Reviews any document (plan, brainstorm, spec, ADR, README) or an entire repository by launching **only relevant** review agents selected from a static roster.
- **research**: Answers research questions by dispatching **only relevant** research agents, collecting findings in parallel, and synthesizing a unified answer with source attribution.

Follow each phase in order. Do NOT skip phases.

**File organization:** This skill is split across phase files. Read each phase file as you reach it — do NOT pre-load all files upfront. Key references:
- `phases/shared-contracts.md` — output format, completion signals (read before Phase 2 dispatch)
- `phases/slicing.md` — content routing patterns and algorithms (read only when slicing activates: diff >= 1000 lines or document >= 200 lines)
- `phases/launch.md` — agent dispatch protocol (read at Phase 2)
- `phases/expansion.md` — AgentDropout + staged expansion (read only when Stage 2 candidates exist)
- `phases/reaction.md` — reaction round (read only when reaction is enabled in config)

## Mode

Determine the mode from the user's invocation:

- If invoked via `/interflux:flux-drive` → `MODE = review`
- If invoked via `/interflux:flux-research` → `MODE = research`
- If the user explicitly passes `--mode=research` or `--mode=review` → use that
- Default: `MODE = review`

The mode gates behavior throughout all phases. Look for **[review only]** and **[research only]** markers below.

## Flags

- `--interactive`: Restore confirmation gates before agent dispatch. Without this flag, the orchestrator auto-proceeds after displaying the triage result. Use `--interactive` when you want to review and edit the agent selection before launch.
- `--output-dir <path>`: Override the default timestamped OUTPUT_DIR with a fixed path (enables iterative reviews of the same document).

Set: `INTERACTIVE = true` if `--interactive` is present, `false` otherwise.

## Input

**[review mode]**: The user provides a file path, directory path, or inline text/topic as an argument. If no argument is provided, ask for one using AskUserQuestion.

**[research mode]**: The user provides a research question as an argument. If no question is provided, ask for one using AskUserQuestion.

### Review mode input detection

Detect the input type and derive paths for use throughout all phases:

```
INPUT_PATH = <the path or text the user provided>
```

Then detect:
- If `INPUT_PATH` is a **file** AND content starts with `diff --git` or `--- a/`: `INPUT_FILE = INPUT_PATH`, `INPUT_DIR = <directory containing file>`, `INPUT_TYPE = diff`
- If `INPUT_PATH` is a **file** (non-diff): `INPUT_FILE = INPUT_PATH`, `INPUT_DIR = <directory containing file>`, `INPUT_TYPE = file`
- If `INPUT_PATH` is a **directory**: `INPUT_FILE = none (repo review mode)`, `INPUT_DIR = INPUT_PATH`, `INPUT_TYPE = directory`
- If `INPUT_PATH` is **not a valid path on disk**: `INPUT_TYPE = text`, `INPUT_DIR = CWD`, treat as inline text

**Text input handling:** When `INPUT_TYPE = text`, write the user's text to `{OUTPUT_DIR}/input.md` so agents can read it. Text inputs are treated like `.md` documents for triage — all agents (including cognitive agents) are eligible.

Derive:
```
INPUT_TYPE    = file | directory | diff | text
INPUT_STEM    = <filename without extension, directory basename, or topic as kebab-case (max 50 chars)>
PROJECT_ROOT  = <nearest ancestor directory containing .git, or INPUT_DIR>
OUTPUT_DIR    = {PROJECT_ROOT}/docs/research/flux-drive/{INPUT_STEM}
```

### Research mode input detection

```
RESEARCH_QUESTION = <the question the user provided>
PROJECT_ROOT      = <git root of the current working directory>
INPUT_STEM        = <question converted to kebab-case, max 50 chars, alphanumeric + hyphens>
OUTPUT_DIR        = {PROJECT_ROOT}/docs/research/flux-research/{INPUT_STEM}
INPUT_TYPE        = research
```

**Run isolation:** Append a timestamp to OUTPUT_DIR to prevent cross-run contamination:
```
RUN_TS = $(date +%Y%m%dT%H%M)
OUTPUT_DIR = {OUTPUT_DIR}-{RUN_TS}
```
This is the default because `find -delete` on a shared OUTPUT_DIR races with slow agents from previous runs (e.g., Oracle with a 10-minute timeout). A still-writing agent's `.partial` gets deleted, but when it renames to `.md`, the file reappears — contaminating the new run's synthesis with stale findings.

To reuse a fixed OUTPUT_DIR (e.g., for iterative reviews of the same document), pass `--output-dir <path>` explicitly. In that case, enforce run isolation with the clean approach:
- Remove existing `.md`, `.md.partial`, and `peer-findings.jsonl` files before dispatch.

**Critical:** Resolve `OUTPUT_DIR` to an **absolute path** before using it in agent prompts. Agents inherit the main session's CWD, so relative paths write to the wrong project during cross-project reviews.

---

## Phase 1: Analyze + Static Triage

### Step 1.0: Understand the Project

Check PROJECT_ROOT for build files (Cargo.toml, go.mod, package.json, etc.), read CLAUDE.md/AGENTS.md if present. For file inputs, compare document vs actual codebase. For directory inputs, read README + key source files. If qmd MCP available, search for project conventions. Note any document-codebase divergence as `divergence: [description]` — this is a P0 finding. Use the **actual** tech stack for triage.

### Step 1.0.1: Classify Project Domains

Output: `Project domains: [comma-separated from: game-simulation, web-api, ml-pipeline, cli-tool, mobile-app, embedded-systems, library-sdk, data-pipeline, claude-code-plugin, tui-app, desktop-tauri]` (or `none`). Multiple domains allowed. Feeds into scoring (domain_boost), criteria injection (Step 2.1a).

### Step 1.0.4: Generate Project Agents

`/interflux:flux-gen "Review of {INPUT}: {1-line summary}"` — skip-existing mode (fast when agents exist). If fails, proceed with core agents only.

### Step 1.1: Analyze the Input

**[research mode]**: Build a query profile: `type` (onboarding/how-to/why-is-it/what-changed/best-practice/debug-context/exploratory), `keywords`, `scope` (narrow/medium/broad), `project_domains`, `estimated_depth` (quick=30s, standard=2min, deep=5min). Then skip to Step 1.2.

**[review mode]**: Read the input and extract a structured profile:

```
Document Profile:
- Type: [plan|brainstorm|spec|prd|README|repo-review|other]
- Summary: [1-2 sentences]
- Languages/Frameworks: [from codebase, not just document]
- Domains touched: [architecture, security, performance, UX, data, API, etc.]
- Project domains: [from Step 1.0.1]
- Divergence: [none | description]
- Key codebase files: [3-5 files]
- Section analysis: [section: thin/adequate/deep — 1-line summary]
- Estimated complexity: [small|medium|large]
- Review goal: [1 sentence — adapts to type: plan→gaps/risks, brainstorm→feasibility, PRD→assumptions/scope, spec→ambiguities]
```

**Diff Profile** (when `INPUT_TYPE = diff`): File count, stats (+/-), languages, domains touched, project domains, key files (top 5 by size), commit message, complexity (small <200/medium/large 1000+), slicing eligible (>= 1000 lines).

Do this analysis yourself (no subagents). The profile drives triage in Step 1.2.

### Step 1.2: Select Agents from Roster

**[research mode]**: Skip the review agent scoring below. Instead, use the research agent affinity table:

Score each research agent on a 3-point scale using the query-type → agent affinity table:

| Query Type | Primary (score=3) | Secondary (score=2) | Skip (score=0) |
|---|---|---|---|
| onboarding | repo-research-analyst | learnings-researcher, framework-docs-researcher | best-practices-researcher, git-history-analyzer |
| how-to | best-practices-researcher, framework-docs-researcher | learnings-researcher | repo-research-analyst, git-history-analyzer |
| why-is-it | git-history-analyzer, repo-research-analyst | learnings-researcher | best-practices-researcher, framework-docs-researcher |
| what-changed | git-history-analyzer | repo-research-analyst | best-practices-researcher, framework-docs-researcher, learnings-researcher |
| best-practice | best-practices-researcher | framework-docs-researcher, learnings-researcher | repo-research-analyst, git-history-analyzer |
| debug-context | learnings-researcher, git-history-analyzer | repo-research-analyst, framework-docs-researcher | best-practices-researcher |
| exploratory | repo-research-analyst, best-practices-researcher | git-history-analyzer, framework-docs-researcher, learnings-researcher | — |

**Domain bonus**: If a detected domain has Research Directives for `best-practices-researcher` or `framework-docs-researcher`, add +1 to their score (these agents benefit most from domain-specific search terms).

**Selection**: Launch all agents with score >= 2. Agents with score 0 are skipped entirely. No staged dispatch — all selected agents launch in a single stage.

Then skip to **Step 1.3** (user confirmation).

**[review mode]**: Use the review agent scoring below.

#### Step 1.2a.0: Routing overrides

Read `.claude/routing-overrides.json` if it exists. For each entry with `"action":"exclude"`: apply scope check (domains AND/OR file_patterns — AND logic if both set; reject `..` or `/`-prefixed patterns). Remove matching agents from candidate pool. Warn if excluded agent is cross-cutting (fd-architecture, fd-quality, fd-safety, fd-correctness). Entries with `"action":"propose"` are informational only. Show canary/confidence metadata in triage notes. Discovery nudge: if agent overridden 3+ times this session, suggest `/interspect:correction`.

#### Step 1.2a: Pre-filter agents

Eliminate agents that cannot score >= 1:

**File/directory inputs:**
- fd-correctness: skip unless DB/migrations/concurrency/async/state (or domain has >=3 injection criteria)
- fd-user-product: skip unless PRD/proposal/user-facing
- fd-safety: skip unless security/credentials/deploy/trust
- fd-game-design: skip unless game-simulation domain detected
- fd-architecture, fd-quality: always pass (domain-general)
- fd-performance: always pass for file/dir

**Diff inputs** (use routing patterns from `phases/slicing.md`):
- Each domain agent: skip unless changed files match its priority file patterns or hunks contain its keywords

**Cognitive agents** (fd-systems, fd-decisions, fd-people, fd-resilience, fd-perception): skip unless `.md`/`.txt` document or `text` input with document type PRD/brainstorm/plan/strategy/vision/roadmap/options analysis. NEVER for code/diff. Base scores: 3 (systems/strategy content), 2 (PRD/brainstorm/plan), 1 (technical reference).

#### Step 1.2b: Score agents (0-8 scale)

```
final_score = base_score(0-3) + domain_boost(0-2) + project_bonus(0-1) + domain_agent(0-1) + tier_bonus(-1 to +1)
```

- base: 3=core overlap, 2=adjacent, 1=tangential, 0=excluded (bonuses can't override 0)
- domain_boost: +2 if agent has injection criteria in detected domain profile
- project_bonus: +1 if CLAUDE.md/AGENTS.md exist (Plugin) or always (Project Agent)
- domain_agent: +1 for flux-gen agents matching detected domain
- tier_bonus: Read from `.claude/agents/.index.yaml` (cache). +1.0 if tier=proven, +0.5 if tier=used, +0 if tier=generated, -1.0 if tier=stub AND use_count=0 AND lines≤80. If index is missing, tier_bonus=0 (don't fail). Rebuild with `/interflux:flux-agent index`.
- Selection: base >= 3 always included, >= 2 if slots remain, >= 1 only for thin sections
- Deduplication: exact name match → prefer Project Agent. Partial overlap → keep both.

**Dynamic slot ceiling:** `4(base) + scope(file:0, small-diff:1, large-diff:2, repo:3) + domain(0:0, 1:1, 2+:2)`, hard max 10.

**Stage assignment:** Stage 1 = top 40% of slots (min 2, max 5). Stage 2 = rest. Expansion pool = scored >= 2 but no slot.

Present triage table: Agent | Category | Score | Stage | Est. Tokens | Source | Reason | Action

### Scoring Examples

Read `references/scoring-examples.md` for worked examples and thin-section thresholds.

### Step 1.2c: Budget-Aware Selection

Apply budget constraints from `config/flux-drive/budget.yaml`. See SKILL-compact.md Step 1.2c for the complete algorithm. Key: budget by INPUT_TYPE, per-agent costs from interstat (>= 3 runs) or defaults, slicing multiplier 0.5x, min 2 agents always selected, exempt agents (fd-safety, fd-correctness) never deferred.

### Step 1.2d: Document Section Mapping

**Trigger:** `INPUT_TYPE = file` AND document > 200 lines. Read `phases/slicing.md` → Document Slicing. Output: `section_map` per agent for Step 2.1c. Documents < 200 lines → all agents get full document.

### Step 1.3: Display Triage and Dispatch

**[research mode]**: Display the triage result as a one-line summary: `Research: {N} agents ({agent_names}), depth: {estimated_depth}`.

**[review mode]**: Display the triage table showing all agents, tiers, scores, stages, reasons, and Launch/Skip actions. Then display: `Stage 1: [agent names]. Stage 2 (on-demand): [agent names].`

**Auto-proceed (default):** Proceed directly to Phase 2. No confirmation needed — the triage algorithm is deterministic and the user can inspect the table output.

**Interactive mode** (`INTERACTIVE = true`): Use AskUserQuestion to get approval before proceeding:

```
AskUserQuestion:
  question: "[research] Launching {N} agents. Proceed?" / "[review] Stage 1: [names]. Launch?"
  options:
    - label: "Launch (Recommended)"
    - label: "Edit selection"
    - label: "Cancel"
```

If user selects "Edit selection", adjust and re-present. If "Cancel", stop here.

---

## Agent Roster

**[review mode]**: Read `references/agent-roster.md` for the full review agent roster including:
- Project Agents (`.claude/agents/fd-*.md`)
- Plugin Agents (7 technical + 5 cognitive fd-* agents with subagent_type mappings)
- Cross-AI (Oracle CLI invocation, error handling, slot rules)

**[research mode]**: Use the research agent roster:

| Agent | subagent_type |
|-------|--------------|
| best-practices-researcher | interflux:research:best-practices-researcher |
| framework-docs-researcher | interflux:research:framework-docs-researcher |
| git-history-analyzer | interflux:research:git-history-analyzer |
| learnings-researcher | interflux:research:learnings-researcher |
| repo-research-analyst | interflux:research:repo-research-analyst |

---

## Phase 2: Launch

**Read the launch phase file now:**
- Read `phases/launch.md` (in the flux-drive skill directory)
- The launch phase respects the `MODE` parameter — research mode uses single-stage dispatch without AgentDropout, expansion, or peer findings
- **[review mode only]**: If interserve mode is detected, also read `phases/launch-codex.md`

## Phase 2.5: Reaction Round

**[review mode only]** — skip entirely in research mode.

Read `phases/reaction.md` now.

## Phase 3: Synthesize

**Read the synthesis phase file now:**
- Read `phases/synthesize.md` (in the flux-drive skill directory)
- The synthesis phase respects the `MODE` parameter — research mode delegates to `intersynth:synthesize-research` and skips bead creation and knowledge compounding

**After synthesis completes — record agent usage:**
Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/flux-agent.py {PROJECT_ROOT} record <agent1> <agent2> ...` with the names of all Project Agents (`.claude/agents/fd-*.md`) that were launched in this review. This increments `use_count`, updates `last_used`, and auto-promotes tiers. Skip Plugin Agents. If the script is not found, skip silently — the registry is a best-effort optimization, not a hard dependency.

## Phase 4: Cross-AI Comparison (Optional)

**[review mode only]** — skip entirely in research mode.

**Skip this phase if Oracle was not in the review roster.** For cross-AI options without Oracle, mention `/interpeer:interpeer` in the Phase 3 report.

If Oracle participated, read `phases/cross-ai.md` now.

---

## Integration

**Chains to (user-initiated, after Phase 4 consent gate) [review mode]:**
- `interpeer` — when user wants to investigate cross-AI disagreements

**Suggests (when Oracle absent, in Phase 3 report) [review mode]:**
- `interpeer` — lightweight cross-AI second opinion

**Called by:**
- `/interflux:flux-drive` command (mode=review)
- `/interflux:flux-research` command (mode=research)

**See also:**
- `interpeer/references/oracle-reference.md` — Oracle CLI reference
- `interpeer/references/oracle-troubleshooting.md` — Oracle troubleshooting
- qmd MCP server (via interknow plugin) — semantic search for project documentation and knowledge entries (used in Steps 1.0 and 2.1)
- When interserve mode is active, flux-drive dispatches review agents through Codex CLI instead of Claude subagents. See `clavain:interserve` for Codex dispatch details.
