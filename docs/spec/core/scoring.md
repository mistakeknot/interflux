# Agent Selection Scoring Algorithm

> flux-drive-spec 1.0 | Conformance: Core

## Overview

The scoring algorithm selects and prioritizes review agents based on relevance to the target document, domain context, and project characteristics. It computes a numeric score for each candidate agent, applies a dynamic slot ceiling based on review scope, and assigns agents to staged execution groups. The algorithm balances thoroughness (include all relevant perspectives) with resource efficiency (exclude tangential agents for simple reviews).

## Specification

### Score Formula

```
final_score = base_score + domain_boost + project_bonus + domain_agent_bonus
max_possible = 3 + 2 + 1 + 1 = 7
```

Each component is computed independently and summed. Agents are ranked by `final_score` descending, then selected up to the slot ceiling.

**Conformance note:** Core implementations require `base_score` (0-3) and `project_bonus` (0-1), yielding a 0-4 range. The `domain_boost` and `domain_agent_bonus` components require domain detection (see [extensions/domain-detection.md](../extensions/domain-detection.md)) and are part of the Core + Domains conformance level. Implementations without domain detection set both to 0.

### Base Score (0-3)

The base score represents intrinsic relevance of the agent's domain to the document content:

| Score | Label | Semantics | Selection Rule |
|-------|-------|-----------|----------------|
| 0 | Irrelevant | Wrong language, wrong domain, no relationship to content | Always excluded. Bonuses cannot override irrelevance. |
| 1 | Tangential | Marginally relevant, minor overlap | Include only for thin sections needing depth AND slots remain |
| 2 | Adjacent | Relevant but not primary focus (e.g., performance for API with perf section) | Include if slots remain after score-3 agents |
| 3 | Core | Agent's domain directly overlaps with document focus | Always included if ceiling permits |

> **Why this works:** 0-3 is the minimum granularity needed for consistent human judgment. Four levels map to natural language categories (irrelevant/tangential/adjacent/core) without decision fatigue. More levels (0-5, 0-10) add overhead without improving selection quality. The hard barrier at 0 prevents "maybe relevant" agents from consuming slots via bonuses.

**Assignment Process:**

1. Read document content (plan, diff, file, or directory summary)
2. Identify primary concerns (e.g., "API design", "database migration", "game simulation loop")
3. For each agent, ask: "Does this agent's review criteria directly address the primary concerns?"
   - No relationship → 0
   - Mentions agent's domain in passing (<10% of content) → 1
   - Agent's domain is a secondary concern (10-30% of content) → 2
   - Agent's domain is a primary concern (>30% of content) → 3

### Domain Boost (0-2)

Applied only when `base_score ≥ 1`. Derived from domain profile injection criteria bullet counts:

| Injection Criteria Bullets | Boost |
|----------------------------|-------|
| ≥3 bullets | +2 |
| 1-2 bullets | +1 |
| 0 bullets (no injection criteria) | +0 |

> **Why this works:** Injection criteria bullet count is a proxy for "how much domain-specific guidance exists for this agent." More guidance = higher value from running the agent in that domain. The 3-bullet threshold separates "generic awareness" (1-2 bullets: "check performance") from "deep domain coverage" (3+ bullets: "check N+1 queries, index usage, connection pooling, caching strategy, query complexity").

**Implementation Notes:**

- Injection criteria are stored per-domain in `config/flux-drive/domains/*.md`
- The criteria specify agent behavior adaptations (e.g., "For web-api domain, safety agent checks JWT validation, CORS, rate limiting")
- If no domain is detected, all agents receive +0 (no domain profile loaded)
- If multiple domains are detected, use the domain profile where the agent has the highest bullet count

### Project Bonus (0-1)

| Condition | Bonus |
|-----------|-------|
| Project has `CLAUDE.md` or `AGENTS.md` | +1 |
| Project has neither file | +0 |
| Agent is project-specific (generated via flux-gen) | +1 (always) |

> **Why this works:** Projects with CLAUDE.md/AGENTS.md signal that agents can use codebase-aware mode — they have context about conventions, architecture, and tech stack. This increases agent effectiveness, justifying broader agent selection. Project-specific agents are always valuable because they're generated explicitly for the project's domain/tech stack.

### Domain Agent Bonus (0-1)

| Condition | Bonus |
|-----------|-------|
| Agent is project-specific AND detected domain matches agent specialization | +1 |
| Otherwise | +0 |

> **Why this works:** flux-gen creates agents for specific detected domains (e.g., "simulation-kernel" agent for game-simulation domain). When reviewing content in that same domain, the generated agent has maximum relevance. This bonus ensures generated agents rank above generic plugin agents when their domain is active.

### Pre-Filtering

Applied **before** scoring to reduce the candidate pool. Filters are input-type dependent:

#### File/Directory Inputs

| Agent | Filter Condition | Passes If |
|-------|------------------|-----------|
| correctness | Skip unless data-related keywords present | Document mentions: databases, migrations, data models, concurrency, async, transactions, consistency |
| user-product | Skip unless product-related | Document is PRD, proposal, strategy, or mentions: user flows, UX, UI, customer, product requirements |
| safety | Skip unless deploy-related | Document mentions: security, credentials, auth, deployments, infrastructure, permissions, secrets |
| game-design | Skip unless game-related | game-simulation domain detected OR keywords: gameplay, mechanics, balance, player, NPC, quest, combat, level design |
| architecture | Always passes | — |
| quality | Always passes | — |
| performance | Always passes (for file/directory) | — |

#### Diff Inputs

Use routing patterns from domain profiles:

- **Priority file patterns**: e.g., safety agent prioritized for `**/auth/**`, `**/config/**`, `Dockerfile`
- **Hunk keywords**: e.g., correctness agent prioritized for hunks containing `INSERT`, `UPDATE`, `DELETE`, `BEGIN TRANSACTION`

If an agent has no matching patterns for the diff, it is filtered out (base_score = 0 before scoring begins).

Domain-general agents (architecture, quality, performance) always pass diff filtering.

### Dynamic Slot Ceiling

```
base_slots       = 4                          # minimum for any review

scope_slots:
  - single file:           +0
  - small diff (<500):     +1
  - large diff (500+):     +2
  - directory/repo:        +3

domain_slots:
  - 0 domains detected:    +0
  - 1 domain detected:     +1
  - 2+ domains detected:   +2

generated_slots:
  - has flux-gen agents:   +2
  - no flux-gen agents:    +0

total_ceiling = base + scope + domain + generated
hard_maximum  = 12                            # absolute cap for resource sanity
```

> **Why this works:** The ceiling adapts to review scope. A single-file edit doesn't need 8 agents; a multi-domain repo review might. The formula encodes three heuristics: (1) larger scope = more surface area = more agents needed, (2) multiple domains = more cross-cutting concerns = more agents needed, (3) project-specific agents exist = user invested in comprehensive review = justify higher ceiling. The hard maximum (12) prevents runaway costs while the formula ensures small reviews stay lean.

**Implementation Notes:**

- Diff size measured in changed lines (additions + deletions)
- Domain count from domain detection pass (runs before scoring)
- flux-gen agent presence checked via agent metadata (`category: project`)

### Stage Assignment

Agents are assigned to execution stages based on final score rank:

| Stage | Slot Allocation | Constraints |
|-------|-----------------|-------------|
| Stage 1 | Top 40% of total slots, rounded up | Min: 2, Max: 5 |
| Stage 2 | All remaining selected agents | — |
| Expansion pool | Agents scoring ≥2 but not selected | Available for mid-review escalation |

**Stage 1 Tiebreaker:**

When multiple agents have the same score at the Stage 1 boundary, prioritize by category:

1. Project-specific agents (category: project)
2. Plugin agents (category: plugin)
3. Cross-AI agents (category: cross-ai)

**Example:**

- Total ceiling: 7 slots
- Stage 1: 40% of 7 = 2.8 → round up to 3
- Stage 2: 7 - 3 = 4 slots
- Top 3 agents go to Stage 1, next 4 go to Stage 2

> **Why this works:** Two stages enable parallelism (Stage 1 runs concurrently) while preserving priority (highest-value agents run first, can block Stage 2 if critical issues found). The 40% ratio balances concurrency (want multiple Stage 1 agents for speed) with focus (too many Stage 1 agents dilutes quality). The 2-5 constraint prevents degenerate cases (1-agent Stage 1 loses parallelism benefit; 8-agent Stage 1 is too diffuse).

### Selection Rules

Applied in order after scoring:

1. **Strong relevance**: All agents scoring ≥3 are included (up to ceiling)
2. **Moderate relevance**: Agents scoring 2 are included if slots remain
3. **Thin section補填**: Agents scoring 1 are included only if:
   - Their domain covers a section flagged as "thin" (<5 lines or <3 bullets), AND
   - Slots remain after rules 1-2
4. **Deduplication**: When multiple agents cover the same domain (e.g., project-specific safety agent vs. plugin safety agent):
   - Project Agent > Plugin Agent > Cross-AI Agent
   - Lower-priority duplicate is excluded (does not consume a slot)

**Thin Section Thresholds:**

| Label | Criteria |
|-------|----------|
| Thin | <5 lines of prose OR <3 bullet points |
| Adequate | 5-30 lines OR 3-10 bullets |
| Deep | 30+ lines OR 10+ bullets |

Thin sections are identified during document analysis (before scoring). Example: a plan with 2 lines on performance ("We'll optimize later") flags performance as thin. If the performance agent scores 1 (tangential), it may be included to force deeper coverage.

## Worked Examples

### Example 1: Go API Plan (web-api domain, has CLAUDE.md)

**Input:**
- Document: 200-line plan for REST API with auth, database, caching
- Detected domain: web-api
- Project has CLAUDE.md
- No flux-gen agents

**Ceiling Calculation:**
```
base:      4
scope:     +0 (single file)
domain:    +1 (1 domain)
generated: +0 (no flux-gen agents)
total:     5 slots
```

**Stage 1 Slots:** 40% of 5 = 2

**Agent Scores:**

| Agent | Base | Domain Boost | Project | Total | Rationale |
|-------|------|--------------|---------|-------|-----------|
| architecture | 3 | +2 (5 injection items for web-api) | +1 | 6 | Core: API design is architectural |
| safety | 3 | +1 (2 injection items) | +1 | 5 | Core: auth + credentials mentioned |
| quality | 2 | +1 (5 injection items) | +1 | 4 | Adjacent: code quality is secondary concern |
| performance | 1 | +1 (5 injection items) | +1 | 3 | Tangential: caching mentioned but <10% of plan |
| correctness | 0 | — | — | 0 | Irrelevant: no database migrations/data modeling (filtered) |
| user-product | 0 | — | — | 0 | Irrelevant: not a PRD, no user flows (filtered) |
| game-design | 0 | — | — | 0 | Irrelevant: not game-related (filtered) |

**Selection:**
- Stage 1: architecture (6), safety (5) — top 2
- Stage 2: quality (4), performance (3)
- Expansion pool: none (all score-2+ agents selected)

### Example 2: Game Project Plan (game-simulation domain, CLAUDE.md, flux-gen agents)

**Input:**
- Document: 400-line plan for turn-based strategy game (simulation kernel, AI, combat, UI)
- Detected domain: game-simulation
- Project has CLAUDE.md
- Has 2 flux-gen agents: simulation-kernel (project-specific), game-ai (project-specific)

**Ceiling Calculation:**
```
base:      4
scope:     +0 (single file)
domain:    +1 (1 domain)
generated: +2 (has flux-gen agents)
total:     7 slots
```

**Stage 1 Slots:** 40% of 7 = 2.8 → 3

**Agent Scores:**

| Agent | Category | Base | Domain | Project | DA | Total | Rationale |
|-------|----------|------|--------|---------|-----|-------|-----------|
| simulation-kernel* | Project | 3 | +2 (5 items) | +1 | +1 | 7 | Core domain + generated for game-simulation |
| game-ai* | Project | 3 | +2 (5 items) | +1 | +1 | 7 | Core domain + generated for game-simulation |
| game-design | Plugin | 3 | +2 (5 items) | +1 | — | 6 | Core: gameplay mechanics are primary |
| architecture | Plugin | 3 | +1 (2 items) | +1 | — | 5 | Core: system design for game loop |
| correctness | Plugin | 2 | +2 (5 items) | +1 | — | 5 | Adjacent: simulation state consistency |
| performance | Plugin | 2 | +1 (5 items) | +1 | — | 4 | Adjacent: turn processing perf mentioned |
| quality | Plugin | 2 | +1 (2 items) | +1 | — | 4 | Adjacent: code quality is secondary |
| safety | Plugin | 1 | +1 (2 items) | +1 | — | 3 | Tangential: no deploy/auth concerns |
| user-product | Plugin | 0 | — | — | — | 0 | Irrelevant: not a product spec (filtered) |

*Generated via flux-gen. DA = domain_agent bonus.

**Tiebreaker for Stage 1 (3 slots, but simulation-kernel and game-ai both score 7):**

Both project-specific agents score 7. game-design scores 6. Stage 1 gets: simulation-kernel, game-ai, game-design (top 3 by score, ties broken by category: project > plugin).

**Selection:**
- Stage 1: simulation-kernel (7), game-ai (7), game-design (6)
- Stage 2: architecture (5), correctness (5), performance (4), quality (4)
- Expansion pool: safety (3) — scored ≥2 but ceiling reached

### Example 3: Small Database Migration Diff (data-pipeline domain, no CLAUDE.md)

**Input:**
- Diff: +120/-45 lines, single migration file adding indexes
- Detected domain: data-pipeline
- No project docs (no CLAUDE.md)
- No flux-gen agents

**Ceiling Calculation:**
```
base:      4
scope:     +1 (small diff <500)
domain:    +1 (1 domain)
generated: +0
total:     6 slots
```

**Stage 1 Slots:** 40% of 6 = 2.4 → 3

**Agent Scores:**

| Agent | Base | Domain | Project | Total | Rationale |
|-------|------|--------|---------|-------|-----------|
| correctness | 3 | +2 (5 items for data-pipeline) | +0 | 5 | Core: migration correctness is primary |
| architecture | 2 | +1 (2 items) | +0 | 3 | Adjacent: index design affects arch |
| safety | 1 | +1 (2 items) | +0 | 2 | Tangential: migration script security |
| quality | 1 | +1 (5 items) | +0 | 2 | Tangential: migration code quality |
| performance | 2 | +1 (5 items) | +0 | 3 | Adjacent: indexes affect query perf |
| user-product | 0 | — | — | 0 | Irrelevant (filtered) |
| game-design | 0 | — | — | 0 | Irrelevant (filtered) |

**Selection:**
- Stage 1: correctness (5), architecture (3), performance (3) — top 3 (tie broken alphabetically for same score)
- Stage 2: safety (2), quality (2)
- Expansion pool: none

## Interflux Reference

### Implementation Files

| Component | Location | Notes |
|-----------|----------|-------|
| Scoring algorithm | `skills/flux-drive/SKILL.md` | Lines 225-332: score calculation and selection logic |
| Worked examples | `skills/flux-drive/references/scoring-examples.md` | Extended examples with edge cases |
| Domain profiles | `config/flux-drive/domains/*.md` | Injection criteria per domain (11 domains) |
| Domain index | `config/flux-drive/domains/index.yaml` | Domain detection rules and agent affinity mappings |
| Pre-filter rules | `config/flux-drive/domains/index.yaml` | `routing_patterns` section per agent |

### Agent Metadata Schema

Agent manifests (`.md` frontmatter or separate `.json`) must include:

```yaml
category: plugin | project | cross-ai
domain: [list of primary domains]
injection_criteria:
  domain-name:
    - criterion 1
    - criterion 2
    ...
```

### Orchestrator Integration

The orchestrator calls the scoring algorithm during the "selection" phase:

1. Parse input (file/diff/directory)
2. Detect domains → load domain profiles
3. Pre-filter agents → candidate pool
4. Score each candidate → ranked list
5. Apply slot ceiling → selected agents
6. Assign stages → execution plan

## Conformance

Implementations of the flux-drive specification:

### MUST

- Implement `base_score` (0-3) with the irrelevant/tangential/adjacent/core semantics
- Implement `project_bonus` (0-1) based on project documentation presence
- Exclude agents with `base_score = 0` regardless of bonuses
- Implement a slot ceiling mechanism (fixed or dynamic)
- Implement stage assignment with at least 2 stages
- Apply pre-filtering before scoring (at minimum: filter irrelevant agents)

### SHOULD

- Implement `domain_boost` (0-2) when domain detection is available (Core + Domains conformance)
- Implement `domain_agent_bonus` (0-1) when project-specific agents and domain detection are available (Core + Domains conformance)
- Implement dynamic slot ceiling that adapts to review scope (scope_slots + domain_slots)
- Use the 40% Stage 1 ratio (or document deviation with rationale)
- Maintain an expansion pool of score-2+ agents for mid-review escalation

### MAY

- Use different score ranges with equivalent semantics (e.g., 0-5 if granularity is preserved and 0 remains a hard barrier)
- Use different stage assignment ratios (document rationale: 40% balances parallelism and focus)
- Add implementation-specific bonuses (e.g., +1 for agents recently updated) if documented
- Implement more than 2 stages (e.g., Stage 3 for long-running Cross-AI agents)

### MUST NOT

- Allow bonuses to override `base_score = 0` (irrelevance is absolute)
- Exceed `hard_maximum = 12` total slots (resource sanity)
- Assign fewer than 2 agents to Stage 1 when ceiling permits (violates parallelism goal)
