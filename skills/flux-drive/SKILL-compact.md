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

**Cache check:** `{PROJECT_ROOT}/.claude/flux-drive.yaml` — if exists with `domains:`, use cached. If `override: true`, never re-detect.

**Detection:** `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/detect-domains.py {PROJECT_ROOT} --json`
- Exit 0: domains detected, use output
- Exit 1: no domains, proceed with core agents only
- Exit 2: script error, proceed with core agents only

**Staleness:** `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/detect-domains.py {PROJECT_ROOT} --check-stale`
- Exit 0: fresh. Exit 3: stale (re-detect). Exit 4: no cache (detect).

### Step 1.0.4: Agent Generation

If domains detected but no `{PROJECT_ROOT}/.claude/agents/fd-*.md` exist, generate them using domain profiles from `config/flux-drive/domains/{domain}.md`.

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

### Step 1.3: User Confirmation

Present triage table: Agent | Score | Stage | Reason | Action

AskUserQuestion: "Stage 1: [names]. Stage 2: [names]. Launch?"
Options: Approve, Edit selection, Cancel.

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
