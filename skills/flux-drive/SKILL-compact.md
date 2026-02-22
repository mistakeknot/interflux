# Flux Drive — Compact Review Instructions

Multi-agent document/codebase review. Follow phases in order.

## Input

User provides a file or directory path. Detect type:

```
INPUT_TYPE = file | directory | diff (starts with "diff --git" or "--- a/")
INPUT_STEM = filename without extension, or dir basename
PROJECT_ROOT = nearest .git ancestor or INPUT_DIR
OUTPUT_DIR = {PROJECT_ROOT}/docs/research/flux-drive/{INPUT_STEM}  (absolute path!)
```

Clean OUTPUT_DIR of stale `.md` files before starting.

## Phase 1: Analyze + Triage

### Step 1.0: Project Understanding

1. Check PROJECT_ROOT for build files (Cargo.toml, go.mod, package.json, etc.)
2. Read CLAUDE.md/AGENTS.md if present
3. If qmd MCP available, search for project conventions

### Step 1.0.1: Domain Detection

**Cache check:** `{PROJECT_ROOT}/.claude/flux-drive.yaml` — if exists with `domains:` and `content_hash:` matches current files, use cached. If `override: true`, never re-detect.

**Detection:** Launch Haiku subagent (Task tool, `model: haiku`) with README + build file + 2-3 key source files. Prompt asks for `{"domains": [{"name", "confidence", "reasoning"}]}` from 11 known domains. Cache result with `source: llm` and `content_hash`.

**Fallback:** If Haiku fails: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/detect-domains.py {PROJECT_ROOT} --json`. Mark `source: heuristic`.

**Staleness:** Compare `content_hash` in cache vs current file hashes. No hash or mismatch → stale (re-detect). Match → fresh.

### Step 1.0.4: Agent Generation

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py {PROJECT_ROOT} --mode=regenerate-stale --json
```
Exit 0: parse JSON report (created/skipped/regenerated/orphaned per agent). Exit 1: no domains. Exit 2: error. Report orphans, don't delete.

### Step 1.1: Document Profile

Read the input. Extract:

```
Type: [plan|brainstorm|spec|prd|README|repo-review|diff|other]
Summary: [1-2 sentences]
Languages/Frameworks: [from codebase, not just doc]
Domains touched: [architecture, security, performance, UX, data, API, etc.]
Project domains: [from 1.0.1]
Divergence: [none | description]
Key codebase files: [3-5 files]
Estimated complexity: [small|medium|large]
Review goal: [1 sentence]
```

For diffs: also extract file count, stats (+/-), slicing eligible (>=1000 lines).

### Step 1.2: Select Agents

**Step 1.2a.0: Routing Overrides** — Read `.claude/routing-overrides.json` if exists. Exclude any agent with `"action":"exclude"`. Warn if excluded agent covers a cross-cutting domain (architecture, quality).

**Step 1.2a: Pre-filter** — Eliminate agents that cannot score >=1:
- fd-correctness: skip unless DB/migrations/concurrency/async
- fd-user-product: skip unless PRD/proposal/user-facing
- fd-safety: skip unless security/credentials/deploy/trust
- fd-game-design: skip unless game-simulation domain detected
- fd-architecture, fd-quality: always pass (domain-general)
- fd-performance: always pass for file/dir; filter for diffs
- fd-systems, fd-decisions, fd-people, fd-resilience, fd-perception: skip unless `.md`/`.txt` document input (PRD, brainstorm, plan, strategy) — NEVER for code/diff

**Step 1.2b: Score** (0-7 scale):

```
final_score = base_score(0-3) + domain_boost(0-2) + project_bonus(0-1) + domain_agent(0-1)
```

- base 3=core domain overlap, 2=adjacent, 1=tangential, 0=excluded
- domain_boost: +2 if agent has >=3 injection criteria for detected domain, +1 for 1-2
- project_bonus: +1 if CLAUDE.md/AGENTS.md exist (Plugin Agents), +1 for Project Agents
- Selection: all >=3 included, >=2 if slots remain, >=1 only for thin sections

**Dynamic slot ceiling:**

```
total = 4(base) + scope(file:0, small-diff:1, large-diff:2, repo:3) + domain(0:0, 1:1, 2+:2) + generated(flux-gen:2, none:0)
hard_max = 12
```

**Stage assignment:** Stage 1 = top 40% of slots (min 2, max 5). Stage 2 = remainder.

### Step 1.2c: Budget-aware agent selection

After scoring and stage assignment, apply budget constraints.

**Step 1.2c.1: Load budget config**

Read `${CLAUDE_PLUGIN_ROOT}/config/flux-drive/budget.yaml`. Look up the budget for the current `INPUT_TYPE`:
- `file` → use the `Document Profile → Type` value (plan, brainstorm, prd, spec, other)
- `diff` with < 500 lines → `diff-small`
- `diff` with >= 500 lines → `diff-large`
- `directory` → `repo`

If a project-level override exists at `{PROJECT_ROOT}/.claude/flux-drive-budget.yaml`, use that instead.

**Sprint budget override:** If `FLUX_BUDGET_REMAINING` env var is set and non-zero, apply: `effective_budget = min(yaml_budget, FLUX_BUDGET_REMAINING)`. This allows sprint-level budget constraints to cap flux-drive dispatch. Note in triage summary: `[sprint-constrained]` when sprint budget is tighter.

Store as `BUDGET_TOTAL`.

**Step 1.2c.2: Estimate per-agent costs**

Run the cost estimator:
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/estimate-costs.sh --model {current_model} [--slicing if slicing active]
```

For each selected agent, look up its estimate:
1. If `estimates[agent_name]` exists (from interstat, >= 3 runs): use `est_tokens`, note `source: interstat (N runs)`
2. Else: classify agent (review/cognitive/research/oracle/generated) and use `defaults[type]`, note `source: default`
3. If slicing is active AND agent is domain-specific (NOT fd-architecture or fd-quality, which always review full content): multiply estimate by `slicing_multiplier`

**Step 1.2c.3: Apply budget cut**

Budget cuts Stage 2 first. Stage 1 agents are always selected (protected). After Stage 1 is fully allocated, add Stage 2 agents by score until budget is exceeded:

```
cumulative = 0
# Stage 1 is always selected (protected)
for agent in stage_1_agents:
    agent.action = "Selected"
    cumulative += agent.est_tokens

# Stage 2 fills remaining budget
for agent in stage_2_agents_sorted_by_score:
    if cumulative + agent.est_tokens > BUDGET_TOTAL and agents_selected >= min_agents:
        agent.action = "Deferred (budget)"
    else:
        agent.action = "Selected"
        cumulative += agent.est_tokens
```

`min_agents` comes from budget.yaml (default 2). Stage 1 always has at least `min_agents`.

**Stage interaction:** If Stage 1 alone exceeds budget, all Stage 1 agents still launch (stage boundaries override budget). Stage 2 agents are deferred by default when budget is tight. The expansion decision (Step 2.2b) will still offer the user the option to override.

**No-data graceful degradation:** If interstat DB doesn't exist or returns no data, use defaults for ALL agents. Log: "Using default cost estimates (no interstat data)." Do NOT skip budget enforcement — defaults provide reasonable bounds.

### Step 1.3: User Confirmation

Present triage table with budget context:

Agent | Score | Stage | Est. Tokens | Source | Reason | Action

After the table, add a budget summary line:
Budget: {cumulative_selected}K / {BUDGET_TOTAL/1000}K ({percentage}%) | Deferred: {N} agents ({deferred_total}K est.)

If agents were deferred, include an override option:
AskUserQuestion: "Stage 1: [names]. Stage 2: [names]. Launch?"
Options: Approve, Launch all (override budget), Edit selection, Cancel.

## Agent Roster

| Agent | subagent_type | Domain |
|-------|--------------|--------|
| fd-architecture | interflux:review:fd-architecture | Boundaries, coupling, patterns, complexity |
| fd-safety | interflux:review:fd-safety | Threats, credentials, trust, deploy risk |
| fd-correctness | interflux:review:fd-correctness | Data consistency, races, transactions |
| fd-quality | interflux:review:fd-quality | Naming, conventions, tests, idioms |
| fd-user-product | interflux:review:fd-user-product | User flows, UX, value prop, scope |
| fd-performance | interflux:review:fd-performance | Bottlenecks, resources, algorithmic complexity |
| fd-game-design | interflux:review:fd-game-design | Balance, pacing, feedback loops, emergent behavior |

**Cognitive Agents** (document review only — `.md`/`.txt` inputs, NEVER code/diff):

| Agent | subagent_type | Domain |
|-------|--------------|--------|
| fd-systems | interflux:review:fd-systems | Feedback loops, emergence, systems dynamics |
| fd-decisions | interflux:review:fd-decisions | Decision traps, biases, uncertainty, paradoxes |
| fd-people | interflux:review:fd-people | Trust, power, communication, team culture |
| fd-resilience | interflux:review:fd-resilience | Antifragility, constraints, resource dynamics |
| fd-perception | interflux:review:fd-perception | Mental models, information quality, sensemaking |

**Project Agents:** `.claude/agents/fd-*.md` — use `subagent_type: general-purpose`, paste file content as prompt.

**Oracle:** `env DISPLAY=:99 CHROME_PATH=/usr/local/bin/google-chrome-wrapper oracle --wait --timeout 1800 --write-output {OUTPUT_DIR}/oracle-council.md.partial -p "<prompt>" -f "<files>"`
Never use `> file` redirect or external `timeout` with Oracle.

**Research agents** (on-demand, not scored): best-practices-researcher, framework-docs-researcher, git-history-analyzer, learnings-researcher, repo-research-analyst.

## Phase 2: Launch

Read `phases/launch.md` for the full launch protocol:
- Step 2.1: Dispatch Stage 1 agents in parallel via Task tool (background mode)
- Step 2.1a: Inject domain-specific criteria from domain profiles
- Step 2.1b: For slicing-eligible diffs, apply diff slicing per `phases/slicing.md`
- Step 2.1c: For documents >200 lines, apply document slicing (section_map per agent)
- Step 2.2: Monitor completion, expand Stage 2 if severity warrants
- All agents write to `{OUTPUT_DIR}/{agent-name}.md` with `<!-- flux-drive:complete -->` sentinel

## Phase 3: Synthesize

Read `phases/synthesize.md` for the full synthesis protocol:
- Collect all agent outputs from OUTPUT_DIR
- Deduplicate findings across agents
- Score findings (P0-P3)
- Compute verdict: APPROVE / APPROVE_WITH_FINDINGS / REVISE / REJECT
- Write synthesis to `{OUTPUT_DIR}/synthesis.md`

## Phase 4: Cross-AI (Optional)

Skip if Oracle was not in roster. Otherwise read `phases/cross-ai.md`.

---

*For edge cases, scoring examples, slicing details, or launch protocol specifics, read the full SKILL.md and its phases/ directory.*
