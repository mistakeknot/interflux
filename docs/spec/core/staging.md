# Multi-Stage Agent Dispatch

> flux-drive-spec 1.0 | Conformance: Core

## Overview

The flux-drive protocol separates agent dispatch into multiple stages to optimize resource utilization. Stage 1 launches high-confidence agents immediately in parallel. Stage 2 launches additional agents conditionally based on Stage 1 findings, with user approval required. An optional research dispatch phase between stages enriches context for Stage 2 agents when Stage 1 findings reference external patterns or uncertain best practices.

## Specification

### Two-Stage Design Philosophy

The protocol implements a cost-control mechanism by separating agent dispatch into immediate and conditional stages. Not every review requires every available agent.

> **Why this works:** Most reviews converge after 3-4 agents. Launching all agents upfront wastes resources on reviews where Stage 1 finds nothing or only minor improvements. The two-stage design lets the orchestrator decide whether additional agents are worth the cost based on actual findings, not predictions. This transforms agent dispatch from a fixed-cost operation into a variable-cost operation that scales with review complexity.

### Stage 1 — Immediate Launch

**Trigger:** User invokes flux-drive review workflow.

**Agent Selection:** All agents assigned Stage 1 during scoring (top 40% by relevance score) are candidates for immediate launch.

**Dispatch Behavior:**
- All Stage 1 agents dispatch in parallel, all-at-once
- No dependencies between Stage 1 agents — they run independently
- No serialization or batching within Stage 1

**Monitoring:**
- Orchestrator monitors completion via the [Completion Signal contract](../contracts/completion-signal.md)
- Poll every 30 seconds for completion signals
- Timeout: 5 minutes for Haiku agents, 10 minutes for Sonnet/Opus agents
- After all Stage 1 agents complete → orchestrator reads their Findings Indexes

**Output:** Set of findings with severity (P0/P1/P2), domain tags, and optional external references.

### Research Dispatch — Context Enrichment (Optional)

**Trigger:** After Stage 1 completes but before the expansion decision, if any Stage 1 finding meets research criteria.

**Research Criteria (any match triggers dispatch):**
- Finding references external patterns (e.g., "common pattern in React hooks")
- Finding references framework versions or API changes
- Finding expresses uncertainty about best practices (e.g., "typically recommended", "usually indicates")
- Finding compares multiple approaches without definitive recommendation

**Dispatch Behavior:**
- Research agents run synchronously (wait for result before proceeding)
- Maximum 2 research dispatches per review
- If more than 2 findings qualify, select the 2 with highest severity
- Timeout: 60 seconds per research agent

> **Why this works:** Research agents are lightweight (single-turn, focused queries) and provide high-value context for expansion agents. Running them synchronously keeps the critical path simple — the orchestrator doesn't need to coordinate async research with expansion decisions. The 2-agent limit prevents research from becoming a bottleneck while still covering the most critical knowledge gaps.

**Skip Conditions:**
- All Stage 1 findings are P2/improvements (research won't change expansion decision)
- No Stage 2 agents planned (research results have no consumer)
- No findings reference external patterns (review is purely internal-code focused)

**Output:** Research results are injected into Stage 2 agent prompts as additional context sections. Research findings do NOT feed into expansion scoring — they enrich agent context, not decision logic.

### Domain Adjacency Map

Agents have 2-3 "neighbors" — agents with related domains where a finding in one makes the neighbor more valuable. The adjacency map defines which domain pairs co-occur in practice.

```yaml
adjacency:
  architecture: [performance, quality]
  correctness: [safety, performance]
  safety: [correctness, architecture]
  quality: [architecture, user-product]
  user-product: [quality, game-design]
  performance: [architecture, correctness]
  game-design: [user-product, correctness, performance]
```

> **Why this works:** Adjacency over full-mesh prevents the "everything is connected" problem. A P0 in safety doesn't justify launching game-design — but it does justify launching correctness (data integrity often accompanies security issues) and architecture (security boundaries are architectural concerns). The map encodes which domain combinations actually co-occur in practice, learned from 100+ manual reviews during development.

**Non-adjacent pairs** (e.g., safety ↔ game-design): expansion requires explicit user request, never auto-recommended.

**Symmetry:** The map is intentionally asymmetric. `architecture → [performance, quality]` does not imply `performance → [architecture]`. Direction matters — a performance finding often requires architecture review, but an architecture finding doesn't always require performance review.

### Expansion Scoring Algorithm

For each Stage 2 / expansion pool agent, compute an expansion score based on Stage 1 findings:

```
expansion_score = 0

# Severity signals (from Stage 1 findings)
for each P0 finding in an adjacent agent's domain:
  expansion_score += 3

for each P1 finding in an adjacent agent's domain:
  expansion_score += 2

# Disagreement signals
if Stage 1 agents disagree on a finding (same file/line, different severity or recommendation):
  expansion_score += 2

# Domain signals
if agent has domain injection criteria met (from scoring phase):
  expansion_score += 1
```

**Scoring Example:**

Stage 1 output:
- `fd-safety`: P0 finding on SQL injection in `query.js:45`
- `fd-architecture`: P1 finding on entangled database layer in `models/`

Stage 2 expansion pool: `fd-correctness`, `fd-performance`, `fd-quality`

| Agent | Calculation | Score |
|---|---|---|
| `fd-correctness` | P0 in safety (adjacent) +3, P1 in architecture (adjacent) +2 | **5** |
| `fd-performance` | P1 in architecture (adjacent) +2 | **2** |
| `fd-quality` | P1 in architecture (adjacent) +2 | **2** |

> **Why this works:** The scoring algorithm is intentionally simple — no weights, no normalization, no machine learning. It's a heuristic that maps severity × adjacency to intuitive decisions. The thresholds below were calibrated across 50+ test reviews to balance false positives (launching unnecessary agents) against false negatives (missing important findings).

### Expansion Decision Thresholds

After computing expansion scores for all Stage 2 agents, select the maximum score and apply thresholds:

| max(expansion_scores) | Decision | Orchestrator Behavior |
|---|---|---|
| **≥ 3** | **RECOMMEND expansion** | Present specific agents with reasoning. Default first option: "Launch [agents]". User may decline. |
| **2** | **OFFER expansion** | Present as user's choice with equal weight. No default option. Explain: "Stage 1 found moderate signals. Expand?" |
| **≤ 1** | **RECOMMEND stop** | Present agents but suggest stopping. Default first option: "Stop here — Stage 1 coverage sufficient". |

> **Why this works:** The thresholds map to intuitive situations. ≥3 means a critical finding (P0: +3) in an adjacent domain — clearly worth investigating. Score of 2 means an important finding (P1: +2) or disagreement (+2) — worth considering but not certain. ≤1 means at most domain affinity (+1) — not enough signal to justify the cost. The user always has final say, but the orchestrator guides the default choice based on strength of signal.

**Multi-agent expansion:** If multiple agents score ≥3, recommend launching all of them in a single Stage 2 batch. If scores are mixed (e.g., one agent at 5, two at 2), present all options and let user choose subset.

### User Interaction Contract

The expansion decision is **always** presented to the user. The orchestrator **never** auto-expands to Stage 2 without explicit user approval.

**Presentation Format:**

```
Stage 1 complete. 4 agents reviewed 23 files.

Findings:
- P0: SQL injection in query.js (fd-safety)
- P1: Entangled database layer (fd-architecture)
- P2: 3 minor style issues (fd-quality)

Expansion recommendation: LAUNCH
- fd-correctness (score: 5) — P0 in safety + P1 in architecture
- fd-performance (score: 2) — P1 in architecture

Options:
1. Launch fd-correctness + fd-performance (recommended)
2. Launch fd-correctness only
3. Stop here

Choice:
```

> **Why this works:** The orchestrator is an advisor, not an autonomous agent. Expansion costs real time and money — users deserve visibility into why expansion is recommended and the ability to override. The multi-option format (not binary yes/no) gives users granular control: launch all, launch subset, or stop.

**Justification requirement:** When recommending expansion, the orchestrator MUST cite specific findings and adjacency relationships that drove the recommendation. "Launch fd-correctness (score: 5)" is insufficient. "Launch fd-correctness — P0 SQL injection in safety domain + P1 architecture finding in adjacent domains" is correct.

### Stage 2 — Conditional Launch

**Trigger:** User approves expansion (full or subset).

**Agent Selection:** User-approved subset of expansion pool agents.

**Dispatch Behavior:**
- All approved Stage 2 agents dispatch in parallel
- No dependencies between Stage 2 agents
- Stage 2 agents MAY receive additional context from research dispatch (if research ran between stages)

**Monitoring:**
- Same monitoring contract as Stage 1 (completion signal, polling, timeout)
- Timeout values unchanged (5m/10m based on model tier)

**Output:** Additional findings that merge with Stage 1 findings for synthesis phase.

> **Why this works:** Stage 2 uses identical dispatch/monitoring logic to Stage 1 — the only difference is when it runs and what context agents receive. This keeps the implementation simple (one dispatch path, two invocation points) and makes the protocol easy to reason about.

### Edge Cases and Boundary Conditions

**No Stage 1 findings:**
- Skip research dispatch (nothing to research)
- Skip expansion scoring (no severity signals)
- Recommend stop with reasoning: "Stage 1 found no issues. Stop here or expand anyway?"
- User may still choose to launch Stage 2 agents (low-probability but supported)

**All Stage 1 agents fail:**
- Treat as "no findings" case above
- Present expansion as fallback: "Stage 1 agents failed. Launch Stage 2 for coverage?"

**Research dispatch timeout:**
- Continue to expansion decision without research results
- Log research timeout but do not block review progression
- Stage 2 agents receive best-effort context (may be incomplete)

**User declines expansion:**
- Proceed directly to synthesis with Stage 1 findings only
- Do not re-prompt or suggest expansion again

**Stage 2 produces no new findings:**
- Not an error — synthesis includes Stage 1 + Stage 2 (empty set)
- Findings Report notes: "Stage 2 agents found no additional issues"

## Interflux Reference

**Implementation Locations:**

- **Expansion algorithm:** `skills/flux-drive/phases/launch.md` (lines 146-220)
  - Scoring logic: lines 165-180
  - Threshold decision table: lines 185-200
  - User interaction contract: lines 205-220

- **Adjacency map:** `skills/flux-drive/phases/launch.md` (lines 75-90, YAML block)

- **Stage assignment logic:** `skills/flux-drive/SKILL.md` (lines 320-325)
  - "Top 40% by score → Stage 1" rule
  - Remaining agents → Stage 2 expansion pool

- **Research dispatch:** `skills/flux-research/SKILL.md` (lines 85-120)
  - Research criteria matching
  - Synchronous dispatch contract

- **Monitoring contract:** `contracts/completion-signal.md` (spec) / `skills/flux-drive/phases/shared-contracts.md` (implementation)
  - Completion signal format
  - Polling intervals and timeouts

**Implementation Notes:**

- Expansion scoring is computed in the orchestrator's context (single turn), not delegated to agents
- Domain adjacency map is hardcoded in `launch.md` (not dynamically learned)
- Research dispatch is optional progressive enhancement — if research agents are not available (model tier limit, quota exhaustion), expansion proceeds without research context
- Stage 2 agents receive research results via prompt injection (appended to task description), not via separate context files

## Conformance

Implementations of the flux-drive staging protocol:

**MUST:**
- Support at least 2 dispatch stages (immediate + conditional)
- Implement an expansion decision mechanism between stages
- Present expansion decisions to the user (never auto-expand without approval)
- Provide reasoning for expansion recommendations (cite findings + adjacency)
- Support user declining expansion (stop after Stage 1)

**SHOULD:**
- Use adjacency maps to scope expansion (not full-mesh)
- Implement severity-based expansion scoring (P0 > P1 > domain affinity)
- Support research dispatch between stages for context enrichment
- Use threshold values ≥3 (recommend), 2 (offer), ≤1 (recommend stop)
- Poll for completion signals every 30 seconds with 5m/10m timeouts

**MAY:**
- Use different threshold values (calibrate for specific domains or cost models)
- Implement more than 2 stages for very large reviews (e.g., Stage 3 for >10 agents)
- Use different adjacency maps (domain-specific or learned from review history)
- Support weighted scoring (e.g., P0 in own domain worth more than P0 in adjacent domain)
- Auto-expand in specific cases IF documented in orchestrator's initial prompt (e.g., "always launch all agents in high-risk domains")

**MUST NOT:**
- Auto-expand without user approval (violates cost control principle)
- Skip Stage 1 and launch all agents immediately (defeats staging purpose)
- Block expansion based on Stage 1 findings alone (user always has override)
