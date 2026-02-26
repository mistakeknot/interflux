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

**File organization:** This skill is split across phase files for readability. Read `phases/shared-contracts.md` and `phases/slicing.md` first (defines output format, completion signals, and content routing), then read each phase file as you reach it.

## Mode

Determine the mode from the user's invocation:

- If invoked via `/interflux:flux-drive` → `MODE = review`
- If invoked via `/interflux:flux-research` → `MODE = research`
- If the user explicitly passes `--mode=research` or `--mode=review` → use that
- Default: `MODE = review`

The mode gates behavior throughout all phases. Look for **[review only]** and **[research only]** markers below.

## Input

**[review mode]**: The user provides a file or directory path as an argument. If no path is provided, ask for one using AskUserQuestion.

**[research mode]**: The user provides a research question as an argument. If no question is provided, ask for one using AskUserQuestion.

### Review mode input detection

Detect the input type and derive paths for use throughout all phases:

```
INPUT_PATH = <the path the user provided>
```

Then detect:
- If `INPUT_PATH` is a **file** AND content starts with `diff --git` or `--- a/`: `INPUT_FILE = INPUT_PATH`, `INPUT_DIR = <directory containing file>`, `INPUT_TYPE = diff`
- If `INPUT_PATH` is a **file** (non-diff): `INPUT_FILE = INPUT_PATH`, `INPUT_DIR = <directory containing file>`, `INPUT_TYPE = file`
- If `INPUT_PATH` is a **directory**: `INPUT_FILE = none (repo review mode)`, `INPUT_DIR = INPUT_PATH`, `INPUT_TYPE = directory`

Derive:
```
INPUT_TYPE    = file | directory | diff
INPUT_STEM    = <filename without extension, or directory basename for repo reviews>
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

**Run isolation:** Before launching agents, clean or verify the output directory:
- If `{OUTPUT_DIR}/` already exists and contains `.md` files, remove them to prevent stale results from contaminating this run.
- Alternatively, append a short timestamp to OUTPUT_DIR (e.g., `{INPUT_STEM}-20260209T1430`) to isolate runs. Use the simpler clean approach by default.

**Critical:** Resolve `OUTPUT_DIR` to an **absolute path** before using it in agent prompts. Agents inherit the main session's CWD, so relative paths write to the wrong project during cross-project reviews.

---

## Phase 1: Analyze + Static Triage

### Step 1.0: Understand the Project

**Before profiling the document**, understand the project's actual tech stack and structure. This is always useful — even for repo reviews.

1. Check the project root for build system files:
   ```bash
   ls {PROJECT_ROOT}/  # Look for Cargo.toml, go.mod, package.json, etc.
   ```
2. For **file inputs**: Compare what the document describes against reality (language, framework, architecture)
3. For **directory inputs**: This IS the primary analysis — read README, build files, key source files
4. If qmd MCP tools are available, run a semantic search for project context:
   - Search for architecture decisions, conventions, and known issues relevant to the document
   - This supplements CLAUDE.md/AGENTS.md reading with broader project knowledge
   - Feed relevant results into the document profile as additional context for triage
5. If there is a **significant divergence** between what a document describes and the actual codebase (e.g., document says Swift but code is Rust+TS):
   - Note it in the document profile as `divergence: [description]`
   - Read 2-3 key codebase files to understand the actual tech stack
   - Use the **actual** tech stack for triage, not the document's
   - All agent prompts must include the divergence context and actual file paths

A document-codebase divergence is itself a P0 finding — every agent should be told about it.

### Step 1.0.1: Classify Project Domain

Detect the project's domain(s) for agent selection and domain-specific review criteria injection. Results are cached.

**Cache check:** Look for `{PROJECT_ROOT}/.claude/intersense.yaml`. If it exists and contains `domains:` with at least one entry, use cached results. If the file also contains `override: true`, never re-detect — the user has manually set their domains.

**Detection** (when no cache, cache is stale, or `source: heuristic` in cache):

Run the deterministic domain detection script:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/detect-domains.py {PROJECT_ROOT} --json
```

This scans directories, files, build-system dependencies, and source keywords against signals defined in domain profiles (shipped with the intersense plugin, with a local fallback at `config/flux-drive/domains/index.yaml`). No LLM call needed.

Parse the JSON output (`{"domains": [...], "source": "deterministic"}`). The script automatically writes the cache to `{PROJECT_ROOT}/.claude/intersense.yaml` with structural hash for staleness detection.

**If detection returns no domains** (exit code 1 or empty list): proceed with core agents only (no domain-specific agents). Log: `"Domain detection: no domains matched, proceeding with core agents only."`

**If detection fails** (exit code 2): proceed with core agents only. Log: `"Domain detection: script error, proceeding with core agents only."`

**Performance budget:** Detection should complete in <5 seconds. Cache check is <10ms.

**Output:** The detected domains feed into Step 1.0.2 (staleness), Step 1.1 (document profile), Step 1.2 (agent scoring with domain bonuses), and Step 2.1a (domain-specific review criteria injection).

### Step 1.0.2: Check Staleness

Check if cached domain detection is outdated using the deterministic content hash helper.

1. Read `content_hash` from `{PROJECT_ROOT}/.claude/intersense.yaml`
2. If no `content_hash` field (old cache format): cache is stale, proceed to Step 1.0.3
3. Run the hash helper to compare:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/content-hash.py {PROJECT_ROOT} --check <cached_hash>
   ```
   - Exit 0: cache is fresh, proceed to Step 1.1
   - Exit 1: cache is stale (hash mismatch or no hashable files), proceed to Step 1.0.3
   - Exit 2: script error, treat as stale, proceed to Step 1.0.3

### Step 1.0.3: Re-detect

When staleness is detected or no cache exists:

1. Read previous domains from cache (if any) for comparison
2. Run LLM detection (Step 1.0.1 detection flow)
3. Compare new vs previous:
   - Unchanged → proceed to Step 1.0.4
   - Changed → log: `"Domain shift: [old] → [new]"`. Proceed to Step 1.0.4

### Step 1.0.4: Agent Generation

Auto-generate project-specific agents using the shared `generate-agents.py` script. This runs non-interactively within the flux-drive pipeline.

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
  "generated": ["fd-simulation-kernel", "fd-agent-narrative"],
  "skipped": ["fd-game-systems"],
  "orphaned": ["fd-old-agent"],
  "errors": []
}
```

**Lists to report:**
- `generated`: Log each: `"Generated: {name}"`
- `skipped`: Silent (agents are current)
- `orphaned`: Log each: `"Orphaned: {name}. Delete manually if unwanted."`
- `errors`: Log as warnings

**Summary line:**
```
Domain agents: N exist, M generated, K orphaned
```

### Step 1.1: Analyze the Input

**[research mode]**: Skip the document profile. Instead build a query profile:

```yaml
query_profile:
  type: <one of: onboarding, how-to, why-is-it, what-changed, best-practice, debug-context, exploratory>
  keywords: [list of key terms extracted from the question]
  scope: <narrow | medium | broad>
  project_domains: [from Step 1.0, if any]
  estimated_depth: <quick | standard | deep>
```

Type detection heuristics:
- "how do I..." / "what's the best way to..." → `how-to`
- "why does..." / "why is..." → `why-is-it`
- "what changed..." / "when did..." → `what-changed`
- "best practice for..." / "conventions for..." → `best-practice`
- "help me understand this codebase..." / "how is this organized..." → `onboarding`
- "I'm debugging..." / "context for this bug..." → `debug-context`
- No clear pattern → `exploratory`

Depth estimation:
- `quick` (30s per agent): simple factual lookups, single-source answers
- `standard` (2min per agent): multi-source synthesis, pattern matching
- `deep` (5min per agent): comprehensive survey, cross-referencing, analysis

Then skip to **Step 1.2** (research agent scoring).

**[review mode]**: For **file inputs**: Read the file at `INPUT_FILE`.
For **repo reviews**: Read README.md (or equivalent), build system files (go.mod, package.json, Cargo.toml, etc.), directory structure (`ls` key directories), and 2-3 key source files.

Extract a structured profile:

```
Document Profile:
- Type: [plan | brainstorm/design | spec/ADR | prd | README/overview | repo-review | other]
- Summary: [1-2 sentence description of what this document is]
- Languages: [from codebase, not just the document]
- Frameworks: [from codebase, not just the document]
- Domains touched: [architecture, security, performance, UX, data, API, etc.]
- Project domains: [from Step 1.0.1 — e.g., "game-simulation (0.65), cli-tool (0.35)" or "none detected"]
- Technologies: [specific tech mentioned]
- Divergence: [none | description — only for documents that describe code]
- Key codebase files: [list 3-5 actual files agents should read]
- Section analysis:
  - [Section name]: [thin/adequate/deep] — [1-line summary]
  - ...
- Estimated complexity: [small/medium/large]
- Review goal: [1 sentence — what should agents focus on?]
```

#### Diff Profile (when `INPUT_TYPE = diff`)

For **diff inputs**, extract a diff-specific profile instead of the document profile above:

```
Diff Profile:
- File count: [N files changed]
- Stats: [+X lines added, -Y lines removed]
- Binary files: [list any binary file changes]
- Languages detected: [from file extensions in the diff]
- Domains touched: [architecture, security, performance, UX, data, API, etc.]
- Project domains: [from Step 1.0.1 — e.g., "game-simulation (0.65), cli-tool (0.35)" or "none detected"]
- Renamed files: [list of old → new renames]
- Key files: [top 5 files by change size]
- Commit message: [if available from diff header]
- Estimated complexity: [small (<200 lines) | medium (200-1000) | large (1000+)]
- Slicing eligible: [yes if total diff lines >= 1000, no otherwise]
- Review goal: "Find issues, risks, and improvements in the proposed changes"
```

Parse the diff to extract file paths and per-file `+`/`-` line counts. For slicing eligibility, count total added + removed lines (excluding diff metadata lines like `@@` hunks and `diff --git` headers).

If `slicing_eligible: yes`, the orchestrator will apply diff slicing in Phase 2 using `phases/slicing.md`. See `phases/launch.md` Step 2.1b.

The `Review goal` adapts to document type:
- Plan → "Find gaps, risks, missing steps"
- Brainstorm/design → "Evaluate feasibility, surface missing alternatives, challenge assumptions"
- README/repo-review → "Evaluate quality, find gaps, suggest improvements"
- Spec/ADR → "Find ambiguities, missing edge cases, implementation risks"
- PRD → "Challenge assumptions, validate business case, find missing user evidence, surface scope risks"
- Other → Infer the appropriate review goal from the document's content

Do this analysis yourself (no subagents needed). The profile drives triage in Step 1.2.

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

#### Step 1.2a.0: Apply routing overrides

Before pre-filtering by content, check for project-level routing overrides:

1. **Read file:** Check if `$FLUX_ROUTING_OVERRIDES_PATH` (default: `.claude/routing-overrides.json`) exists in the project root.
2. **If missing:** Continue to Step 1.2a with no exclusions.
3. **If present:**
   a. Parse JSON. If malformed, log `"WARNING: routing-overrides.json malformed, ignoring overrides"` in triage output, move file to `.claude/routing-overrides.json.corrupted`, and continue with no exclusions.
   b. Check `version` field. If `version > 1`, log `"WARNING: Routing overrides version N not supported (max 1). Ignoring file."` and continue with no exclusions.
   c. Read `.overrides[]` array. For each entry with `"action": "exclude"`:
      - **Scope check:** If the entry has a `scope` field:
        - If `scope.domains` is set, check if the current document's detected domain (from Step 1.1) matches any domain in the list. If no match, skip this override (agent stays in pool).
        - If `scope.file_patterns` is set, check if any input file path matches any glob pattern. If no match, skip this override. Reject patterns containing `..` or starting with `/` as invalid.
        - If both are set, BOTH must match (AND logic).
        - If `scope.file_patterns` contains only `**` (match-all), treat the override as global and apply the cross-cutting agent warning below.
      - If no `scope` field, the override applies globally (all domains, all files).
      - Remove the agent from the candidate pool (they will not appear in pre-filter or scoring).
      - If the agent is not in the roster (unknown name), log: `"WARNING: Routing override for unknown agent {name} — check spelling or remove entry."`
      - If the excluded agent is cross-cutting (fd-architecture, fd-quality, fd-safety, fd-correctness), add a **prominent warning** to triage output: `"Warning: Routing override excludes cross-cutting agent {name}. This removes structural/security coverage."`
   d. Entries with `"action": "propose"` are informational only — do NOT exclude the agent. Log: `"INFO: Proposed exclusion for {name} (not yet active). Run /interspect:propose to review."`
4. **Triage table note:** After the scoring table, add: `"N agents excluded by routing overrides: [agent1, agent2, ...]"`
   - For each excluded agent with a `canary` field, append: `"agent1 [canary: created active, expires 2026-03-09]"` — note this is a creation-time snapshot. Run `/interspect:status` for live canary state.
   - For each excluded agent with a `confidence` field, append: `"(confidence: 0.85)"`
5. **Discovery nudge:** If the same agent has been overridden 3+ times in the current session (via user declining findings or explicitly overriding), add a note after the triage table: `"Tip: Agent {name} was overridden {N} times this session. Run /interspect:correction to record this pattern. After enough evidence, /interspect can propose permanent exclusions."`
6. **Continue to Step 1.2a** with the reduced candidate pool.

#### Step 1.2a: Pre-filter agents

Before scoring, eliminate agents that cannot plausibly score ≥1 based on the document/diff profile:

**For file and directory inputs:**

1. **Data filter**: Skip fd-correctness unless the document mentions databases, migrations, data models, concurrency, or async patterns.
2. **Product filter**: Skip fd-user-product unless the document type is PRD, proposal, strategy document, or has user-facing flows.
3. **Deploy filter**: Skip fd-safety unless the document mentions security, credentials, deployments, infrastructure, or trust boundaries.

**For file and directory inputs (continued):**

4. **Game filter**: Skip fd-game-design unless Step 1.0.1 detected `game-simulation` domain OR the document/project mentions game, simulation, AI behavior, storyteller, balance, procedural generation, tick loop, needs/mood systems, or drama management.

**For all input types (cognitive agent filter):**

5. **Cognitive filter**: Skip fd-systems, fd-decisions, fd-people, fd-resilience, fd-perception unless ALL of these conditions are met:
   - Input type is `file` or `directory` (NOT `diff`)
   - File extension is `.md` or `.txt` (NOT code: `.go`, `.py`, `.ts`, `.tsx`, `.rs`, `.sh`, `.c`, `.java`, `.rb`)
   - Document type matches: PRD, brainstorm, plan, strategy, vision, roadmap, architecture doc, or research document

When cognitive agents pass the pre-filter, assign base_score using these heuristics:
   - base_score 3: Document explicitly discusses systems, feedback, strategy, architecture decisions, or organizational dynamics
   - base_score 2: Document is a PRD, brainstorm, or plan (general document review)
   - base_score 1: Document is `.md` but content is primarily technical reference (API docs, changelogs)

**For diff inputs** (use routing patterns from `phases/slicing.md`):

1. **Data filter**: Skip fd-correctness unless any changed file matches its priority file patterns or any hunk contains its priority keywords.
2. **Product filter**: Skip fd-user-product unless any changed file matches its priority file patterns or any hunk contains its priority keywords.
3. **Deploy filter**: Skip fd-safety unless any changed file matches its priority file patterns or any hunk contains its priority keywords.
4. **Perf filter**: Skip fd-performance unless any changed file matches its priority file patterns or any hunk contains its priority keywords.
5. **Game filter**: Skip fd-game-design unless any changed file matches its priority file patterns or any hunk contains its priority keywords.

Domain-general agents always pass the filter: fd-architecture, fd-quality, and fd-performance (for file/directory inputs only — for diffs, fd-performance is filtered by routing patterns like other domain agents).

Cognitive agents (fd-systems, fd-decisions, fd-people, fd-resilience, fd-perception) are filtered separately by the cognitive filter above and are NEVER included for diff or code file inputs. Cognitive agents display as category `cognitive` in the triage table. Technical agents display as category `technical` (default).

Present only passing agents in the scoring table below.

Score the pre-filtered agents against the document profile using a **0-7 scale**:

```
Score Components:
  base_score:     0-3 (0=irrelevant, 1=tangential, 2=adjacent, 3=core domain)
  domain_boost:   0-2 (from domain profile match — see below)
  project_bonus:  0-1 (project has CLAUDE.md/AGENTS.md)
  domain_agent:   0-1 (for domain-specific generated agents from /flux-gen)

  final_score = base_score + domain_boost + project_bonus + domain_agent
  max possible = 3 + 2 + 1 + 1 = 7
```

> **Note**: Base score 0 means the agent is excluded. Bonuses cannot override irrelevance.

**Base score guide:**
- **3 (core)**: Agent's domain directly overlaps with document content (e.g., fd-safety for a security audit).
- **2 (adjacent)**: Agent's domain is relevant but not the primary focus (e.g., fd-performance for an API plan with a perf section).
- **1 (tangential)**: Agent's domain is marginally relevant. Include only for thin sections that need more depth.
- **0 (irrelevant)**: Wrong language, wrong domain, no relationship. Always excluded.

**Project bonus** (+0 or +1): Plugin Agents get +1 when the target project has CLAUDE.md/AGENTS.md (they auto-detect and use codebase-aware mode). Project Agents get +1 (project-specific by definition).

**Domain boost** (+0, +1, or +2; applied only when base score ≥ 1): When Step 1.0.1 detected a project domain, check each agent's injection criteria in the corresponding domain profile (intersense `config/domains/*.md`, with fallback to local `config/flux-drive/domains/*.md`):
- Agent has injection criteria with ≥3 bullets for this domain → +2
- Agent has injection criteria (1-2 bullets) for this domain → +1
- Agent has no injection criteria for this domain → +0

Domain profiles also provide domain-specific review bullets loaded during Phase 2 (Step 2.1a) and injected into each agent's prompt.

**Domain agent bonus** (+0 or +1): Project-specific agents generated by `/flux-gen` get +1 when the detected domain matches their specialization.

**Selection rules**:
1. All agents scoring 3+ are included (strong relevance)
2. Agents scoring 2 are included if slots remain
3. Agents scoring 1 are included only if their domain covers a thin section AND slots remain
4. **Dynamic slot ceiling** (see below) — replaces hard cap
5. **Deduplication**: If a Project Agent covers the same domain as a Plugin Agent, prefer the Project Agent
6. Prefer fewer, more relevant agents over many marginal ones

#### Dynamic slot allocation

The agent ceiling adapts to review scope and domain density:

```
base_slots    = 4                        # minimum for any review
scope_slots:
  - single file:          +0
  - small diff (<500 lines): +1
  - large diff (500+):    +2
  - directory/repo:       +3
domain_slots:
  - 0 domains detected:   +0
  - 1 domain detected:    +1
  - 2+ domains detected:  +2
generated_slots:
  - project has /flux-gen agents: +2
  - no /flux-gen agents:  +0

total_ceiling = base + scope + domain + generated
hard_maximum  = 12                       # absolute cap for resource sanity
```

**Examples:**
- Single-file review, no domain → 4 slots (lean)
- Repo review, 1 domain → 4+3+1 = 8 slots (standard)
- Repo review, 2 domains, with /flux-gen agents → 4+3+2+2 = 11 slots (full)
- Small diff, no domain → 4+1 = 5 slots (quick check)

#### Stage assignment

After selecting agents, assign dispatch stages:
- **Stage 1**: Top 40% of total slots (rounded up, min 2, max 5). Fill with highest-scoring agents. Ties broken by: Project > Plugin > Cross-AI.
- **Stage 2**: All remaining selected agents
- **Expansion pool**: Agents that scored ≥2 but didn't get a slot — these are candidates for domain-aware expansion after Stage 1 (see `phases/launch.md` Step 2.2b)

Present the triage table with budget context:

| Agent | Category | Score | Stage | Est. Tokens | Source | Reason | Action |
|-------|----------|-------|-------|-------------|--------|--------|--------|

### Scoring Examples

Read `references/scoring-examples.md` for 4 worked examples covering different document types and domain configurations, plus thin-section threshold definitions.

### Step 1.2c: Budget-Aware Selection

After scoring and stage assignment, apply budget constraints using `config/flux-drive/budget.yaml` and the cost estimator at `scripts/estimate-costs.sh`. See the compact skill (SKILL-compact.md Step 1.2c) for the complete algorithm.

Key points:
- Budget lookup by INPUT_TYPE (plan, brainstorm, diff-small, diff-large, repo, etc.)
- Per-agent cost from interstat historical data, falling back to budget.yaml defaults
- Slicing multiplier (0.5x) applied for non-cross-cutting agents when slicing is active
- Minimum 2 agents always selected regardless of budget
- Deferred agents shown in triage table with override option

### Step 1.2d: Document Section Mapping

**Trigger:** `INPUT_TYPE = file` AND document exceeds 200 lines.

Split the document into sections and classify relevance per agent. This reduces token cost by sending domain-specific agents only their relevant sections in full, with one-line summaries for the rest. Cross-cutting agents always receive the full document.

Read `phases/slicing.md` → Document Slicing for the complete classification algorithm, including section heading keywords, safety override, 80% threshold, and pyramid summary rules.

**For documents < 200 lines**, skip this step entirely — all agents receive the full document.

**Output**: A `section_map` per agent, used in Step 2.1c to write per-agent temp files.

### Step 1.3: User Confirmation

**[research mode]**: Present the triage result via AskUserQuestion:

```
AskUserQuestion:
  question: "Research plan for: '{RESEARCH_QUESTION}'. Query type: {type}. Launching {N} agents ({agent_names}). Estimated depth: {estimated_depth}. Proceed?"
  header: "Research"
  options:
    - label: "Launch (Recommended)"
      description: "Dispatch {N} agents in parallel for {estimated_depth} research"
    - label: "Edit agents"
      description: "Add or remove specific agents before launch"
    - label: "Cancel"
      description: "Abort research"
```

If user selects "Edit agents", present a multi-select AskUserQuestion with all 5 agents and let them toggle.
If user selects "Cancel", stop immediately.

**[review mode]**: First, present the triage table showing all agents, tiers, scores, stages, reasons, and Launch/Skip actions.

Then use **AskUserQuestion** to get approval:

```
AskUserQuestion:
  question: "Stage 1: [agent names]. Stage 2 (on-demand): [agent names]. Launch Stage 1?"
  options:
    - label: "Approve"
      description: "Launch Stage 1 agents"
    - label: "Edit selection"
      description: "Adjust stage assignments or agents"
    - label: "Cancel"
      description: "Stop flux-drive review"
```

If user selects "Edit selection", adjust and re-present.
If user selects "Cancel", stop here.

---

## Agent Roster

**[review mode]**: Read `references/agent-roster.md` for the full review agent roster including:
- Project Agents (`.claude/agents/fd-*.md`)
- Plugin Agents (7 technical + 5 cognitive fd-* agents with subagent_type mappings)
- Cross-AI (Oracle CLI invocation, error handling, slot rules)

**[research mode]**: Use the research agent roster:

| Agent | subagent_type |
|-------|--------------|
| best-practices-researcher | interflux:best-practices-researcher |
| framework-docs-researcher | interflux:framework-docs-researcher |
| git-history-analyzer | interflux:git-history-analyzer |
| learnings-researcher | interflux:learnings-researcher |
| repo-research-analyst | interflux:repo-research-analyst |

---

## Phase 2: Launch

**Read the launch phase file now:**
- Read `phases/launch.md` (in the flux-drive skill directory)
- The launch phase respects the `MODE` parameter — research mode uses single-stage dispatch without AgentDropout, expansion, or peer findings
- **[review mode only]**: If interserve mode is detected, also read `phases/launch-codex.md`

## Phase 3: Synthesize

**Read the synthesis phase file now:**
- Read `phases/synthesize.md` (in the flux-drive skill directory)
- The synthesis phase respects the `MODE` parameter — research mode delegates to `intersynth:synthesize-research` and skips bead creation and knowledge compounding

## Phase 4: Cross-AI Comparison (Optional)

**[review mode only]** — skip entirely in research mode.

**Skip this phase if Oracle was not in the review roster.** For cross-AI options without Oracle, mention `/clavain:interpeer` in the Phase 3 report.

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
