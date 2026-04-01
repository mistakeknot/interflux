# Phase 2 Expansion: AgentDropout + Staged Expansion

Read this file only when Stage 2 candidates exist after Stage 1 completes.

### Step 2.2a.5: AgentDropout — redundancy filter [review only]

**Skip this step in research mode** — research mode uses single-stage dispatch with no candidate pool to prune.

After Stage 1 completes (and optional research dispatch), apply a lightweight redundancy check to the Stage 2 and expansion pool candidates. This step prunes agents whose domains are already well-covered by Stage 1 findings, saving tokens without losing coverage.

**When to run:** Always run this step before the expansion decision (Step 2.2b). It modifies the candidate pool that expansion scoring operates on.

**Exempt agents:** Never drop agents listed in `budget.yaml → exempt_agents` (currently `fd-safety`, `fd-correctness`). These always survive dropout regardless of redundancy signals.

#### Redundancy scoring algorithm

For each Stage 2 / expansion pool agent, compute a redundancy score (0.0 – 1.0) based on Stage 1 output:

```
redundancy_score = 0.0

# 1. Domain convergence — Stage 1 already covered this agent's domain
stage1_domains = set of domains that produced P0/P1 findings in Stage 1
if agent's primary domain ∈ stage1_domains:
    redundancy_score += 0.4

# 2. Adjacency saturation — all of this agent's neighbors ran in Stage 1
agent_neighbors = adjacency_map[agent]
neighbors_in_stage1 = [n for n in agent_neighbors if n ran in Stage 1]
if len(neighbors_in_stage1) == len(agent_neighbors):
    redundancy_score += 0.3   # all neighbors already covered

# 3. Finding density — Stage 1 produced many findings in adjacent domains
adjacent_finding_count = count of P0+P1 findings from agents adjacent to this agent
if adjacent_finding_count >= 3:
    redundancy_score += 0.2   # adjacent domains are well-explored

# 4. Low trust signal — agent has poor historical precision
trust_score = trust_multiplier for this agent (from Step 2.1e, default 1.0)
if trust_score < 0.5:
    redundancy_score += 0.1   # low-trust agents are weaker candidates
```

#### Dropout decision

```
DROPOUT_THRESHOLD = 0.6  (from budget.yaml → dropout.threshold, default 0.6)

for each candidate in Stage 2 + expansion pool:
    if candidate in exempt_agents:
        continue  # never dropped
    if redundancy_score >= DROPOUT_THRESHOLD:
        mark candidate as DROPPED
```

#### Logging (always)

```
AgentDropout: Evaluated N candidates (threshold: 0.6)
  ✓ fd-performance (redundancy: 0.4) — retained
  ✗ fd-quality (redundancy: 0.7) — DROPPED (domain converged + neighbors saturated)
  🛡 fd-safety (redundancy: 0.8) — EXEMPT (safety-critical)
Dropped: N agents. Estimated savings: ~NK tokens.
```

**Estimated savings** = sum of `agent_defaults[category]` from `budget.yaml` for each dropped agent (adjusted by `slicing_multiplier` if slicing is active).

#### Token savings tracking

Record dropout decisions in the cost report data for Step 3.4b:

```json
{
  "dropout": {
    "evaluated": 5,
    "dropped": ["fd-quality", "fd-user-product"],
    "retained": ["fd-performance", "fd-game-design"],
    "exempt": ["fd-safety"],
    "estimated_savings": 80000,
    "scores": { "fd-quality": 0.7, "fd-user-product": 0.6, "fd-performance": 0.4, "fd-game-design": 0.1, "fd-safety": 0.8 }
  }
}
```

#### Override

If the user selects "Launch all Stage 2 anyway" in Step 2.2b, dropped agents are restored — dropout is advisory, never a hard gate.

#### Skip conditions

Skip this step entirely when:
- Only 1 Stage 2 candidate exists (nothing to drop)
- Stage 1 produced zero findings (no convergence signal)
- `budget.yaml → dropout.enabled` is `false`

### Step 2.2a.6: Incremental expansion (during Stage 1) [review only]

**Skip this step in research mode.**

As each Stage 1 agent completes (`.md` file appears in `{OUTPUT_DIR}/`):
1. Read its Findings Index
2. For each Stage 2 / expansion pool candidate, compute partial expansion score using only the completed agent's findings
3. If any candidate reaches expansion_score >= 3: launch immediately (max 2 speculative launches)
4. Log: `[speculative Stage 2] Launching {agent} based on {trigger_agent}'s P{severity} finding in {domain}`

Speculative launches do NOT count against the slot ceiling — they are bonus agents justified by Stage 1 evidence.

**Cap:** Maximum 2 speculative launches during Stage 1.

**Skip conditions:**
- Only 1 Stage 1 agent (no partial results to evaluate)
- No Stage 2/expansion candidates exist
- `budget.yaml → incremental_expansion.enabled` is `false`

### Step 2.2b: Domain-aware expansion decision [review only]

**Skip this step in research mode** — all research agents dispatch in a single stage.

After Stage 1 completes (and AgentDropout filtering), read the Findings Index from each Stage 1 output file. Then use the **expansion scoring algorithm** to recommend which Stage 2 agents to launch.

#### Domain adjacency map

```yaml
adjacency:
  fd-architecture: [fd-performance, fd-quality]
  fd-correctness: [fd-safety, fd-performance]
  fd-safety: [fd-correctness, fd-architecture]
  fd-quality: [fd-architecture, fd-user-product]
  fd-user-product: [fd-quality, fd-game-design]
  fd-performance: [fd-architecture, fd-correctness]
  fd-game-design: [fd-user-product, fd-correctness, fd-performance]
```

**Project Agent adjacency (dynamic):**
1. **Domain-mode agents** (`domain:` field): Map to plugin agents whose adjacency domain overlaps.
2. **Prompt-mode agents** (`generated_by: flux-gen-prompt`): Infer domain from `focus`/`review_areas` by keyword matching.
3. **No match**: No adjacency entries — retained during dropout, excluded from expansion scoring.

**Cognitive agents** are excluded from the adjacency map.

#### Expansion scoring algorithm

```
expansion_score = 0
if any P0 in an adjacent agent's domain:    expansion_score += 3
if any P1 in an adjacent agent's domain:    expansion_score += 2
if Stage 1 agents disagree on a finding in this agent's domain: expansion_score += 2
if agent has domain injection criteria for a detected domain: expansion_score += 1
```

#### Expansion decision

| max(expansion_scores) | Decision |
|---|---|
| >= 3 | **RECOMMEND expansion** — present specific agents with reasoning |
| 2 | **OFFER expansion** — user's choice, no default |
| <= 1 | **RECOMMEND stop** — "Stop here" is the default |

Present via AskUserQuestion with reasoning about why each agent should be added. If user chooses expansion, launch only the recommended agents unless they select "Launch all."

### Step 2.2c: Stage 2 — Remaining agents (if expanded) [review only]

**Skip this step in research mode.**

Launch Stage 2 agents with `run_in_background: true`. Wait for completion using the same monitoring mechanism (Step 2.3).
