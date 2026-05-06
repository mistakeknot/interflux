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

**Cross-model dispatch for speculative launches:**

If `cross_model_dispatch.enabled`:
1. Apply speculative discount: `effective_score = max(expansion_score - 1, 1)`
   Note: since speculative triggers at score>=3, discount yields score=2 ("keep model") —
   the discount prevents the score=3 upgrade path, not the base tier. This is intentional:
   speculative evidence is partial, so upgrades shouldn't fire, but the base tier is preserved.
2. Budget pressure: use current `remaining_budget` (no speculative reserve needed — this IS the speculative launch)
3. Call `routing_adjust_expansion_tier(agent, model, effective_score, pressure_label)`
4. If `mode == "shadow"`: log with `[shadow][speculative]` prefix, dispatch at original model
5. If `mode == "enforce"`: dispatch at adjusted model

Log: `[speculative Stage 2] Launching {agent} at {model} (score={original_score}, discounted={effective_score})`

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
expansion_contributions = []  # list of (source_id, score_increment)

for each Stage 1 finding:
    source_id = "{agent}:{finding_index}"  # unique per finding
    if P0 in an adjacent agent's domain:
        expansion_contributions.append((source_id, 3))
    if P1 in an adjacent agent's domain:
        expansion_contributions.append((source_id, 2))

for each Stage 1 agent pair:
    if agents disagree on a finding in this agent's domain:
        source_id = "disagree:{agent_a}:{agent_b}:{finding}"
        expansion_contributions.append((source_id, 2))

if agent has domain injection criteria for a detected domain:
    source_id = "domain:{domain_name}"
    expansion_contributions.append((source_id, 1))

# Deduplication: keep max contribution per source_id (pool-wide)
deduplicated = {}
for (sid, inc) in expansion_contributions:
    deduplicated[sid] = max(deduplicated.get(sid, 0), inc)

expansion_score = min(sum(deduplicated.values()), 3)
```

#### Expansion decision

| max(expansion_scores) | Decision |
|---|---|
| >= 3 | **AUTO-EXPAND** — launch recommended agents with reasoning |
| 2 | **AUTO-EXPAND** — launch recommended agents (evidence supports expansion) |
| <= 1 | **AUTO-STOP** — "Stop here" is the default |

**Auto-proceed (default):** If max score >= 2, auto-expand with recommended agents. If <= 1, auto-stop. Log the expansion decision and reasoning for the user's inspection.

**Interactive mode** (`INTERACTIVE = true`): Always present via AskUserQuestion with reasoning about why each agent should be added. If user chooses expansion, launch only the recommended agents unless they select "Launch all."

#### Pre-dispatch sort (merit order)

Before dispatching Stage 2 agents, sort candidates by:
1. `expansion_score` descending (highest-confidence agents first)
2. `role_priority` descending: planner=4 > reviewer=3 > editor=2 > checker=1
3. `name` ascending (stable tiebreaker)

High-score agents get first claim on budget headroom. Process in this order
for both tier adjustment and dispatch.

#### Domain intersection validation

For each expansion candidate with score > 0:
- Resolve the candidate's primary domain from `adjacency` map or agent focus
- Resolve the trigger finding's domain from the Stage 1 agent that produced it
- If `trigger_domain ∩ candidate_domain == ∅` (no adjacency relationship exists):
  - Log: `[expansion] {agent}: score={score} but no domain overlap with trigger — capping tier at haiku`
  - Set `tier_cap = haiku` for this candidate (applied during cross-model dispatch)
- This check prevents phantom adjacency inflation: a domain-specific P0 should not
  drive a non-adjacent agent to sonnet

### Step 2.2c: Stage 2 — Remaining agents (if expanded) [review only]

**Skip this step in research mode.**

#### Cross-model dispatch (if enabled)

Check feature gate (read from budget.yaml at skill init, not per-dispatch):
```bash
# These values are resolved once during Step 2.0.5 (alongside model resolution)
# and stored as env vars. Do NOT re-read budget.yaml via Python subprocess per dispatch.
# cmd_enabled: "true" | "false"
# cmd_mode: "shadow" | "enforce"
```

If `cmd_enabled == "true"`:

**1. Compute budget pressure:**
```
speculative_reserve = incremental_expansion.max_speculative × agent_defaults.review
effective_budget = remaining_budget - speculative_reserve
pressure_ratio = 1.0 - (effective_budget / sum(stage2_cost_estimates))
pressure_label = "low" if < 0.2, "medium" if 0.2-0.5, "high" if > 0.5
```

**2. First pass — tentative tier adjustment (sorted order):**
For each candidate in merit-order (from pre-dispatch sort):
```
original_model = resolved_model_for(agent)  # from routing_resolve_agents output in Step 2.0.5, or agent frontmatter default
adjusted_model = routing_adjust_expansion_tier(agent, original_model, expansion_score, pressure_label)
# Apply tier_cap from domain intersection check
if tier_cap[agent] == "haiku":
    adjusted_model_tier = _routing_model_tier(adjusted_model)
    if adjusted_model_tier > 1:  # > haiku
        adjusted_model = "haiku"
        adjusted_model = _routing_apply_safety_floor(agent, adjusted_model, "tier-cap")
tentative_adjustments[agent] = adjusted_model
```

**3. Recompute pressure from adjusted costs:**
```
adjusted_total = sum(cost_estimate(agent, tentative_adjustments[agent]) for agent in candidates)
revised_pressure_ratio = 1.0 - (effective_budget / adjusted_total)
revised_pressure_label = classify(revised_pressure_ratio)
```
If `revised_pressure_label` differs from `pressure_label`, run a second pass with the revised pressure. Cap at 2 passes to prevent oscillation.

**4. Downgrade cap:**
```
downgraded_count = count(agents where adjusted_model < original_model)
max_downgrades = floor(len(candidates) / 2)
if downgraded_count > max_downgrades:
    # Restore lowest-scored agents to original model (they were downgraded last in merit order)
    # until downgraded_count <= max_downgrades
    # IMPORTANT: After restoring each agent, reapply:
    #   1. Domain intersection tier_cap check (may re-cap to haiku)
    #   2. _routing_apply_safety_floor (non-negotiable)
```

**5. Upgrade pass (savings recycling):**
```
tokens_saved = sum(cost(original) - cost(adjusted) for each agent)
if tokens_saved > 10000:
    # Find highest-scored score=2 agent that was NOT upgraded
    # Upgrade one tier: haiku→sonnet or sonnet→opus
    # Apply safety floor and max_model ceiling
```

**6. Pool-level quality assertion (runs AFTER upgrade pass):**
```
planner_reviewer_at_sonnet = count(agents where role in (planner, reviewer) AND tier >= sonnet)
if planner_reviewer_at_sonnet == 0:
    # Upgrade highest-scored planner/reviewer to sonnet
```

**7. Shadow vs enforce:**
```
if cmd_mode == "shadow":
    # Log all adjustments with [shadow] prefix
    # Dispatch at original models from Step 2.0.5 map
    # Shadow proxy signal: for each agent that WOULD have been downgraded,
    # log [shadow-proxy] agent={name} original={orig} adjusted={adj} —
    # after completion, check if agent returned P0/P1 at original model.
    # This provides calibration data for the shadow→enforce transition
    # without requiring actual enforcement.
else:
    # Dispatch at adjusted models
```

**8. Dispatch Stage 2 agents** with `run_in_background: true`, passing the final model per agent. Respect the `MAX_CONCURRENT_AGENTS` cap defined in `phases/launch.md` § Concurrency cap (default 6) — Stage 2 typically launches the most agents and is the primary site where the cap matters. If the candidate count exceeds the cap, dispatch in batches: launch up to `MAX_CONCURRENT_AGENTS`, wait for any to complete, then dispatch the next.

#### Dispatch logging (always, when cross-model dispatch enabled)

After dispatch, log the tier adjustment summary:

```
Cross-model dispatch (Stage 2):
  {agent}: {original} → {adjusted} (score={score}, domain_complexity={dc}, {reason})
  ...
  🛡 {agent}: {model} → {floor_model} (safety floor clamped)
Budget pressure: {pressure_ratio:.2f} ({pressure_label}), reserve: {reserve}
Pool audit: {n} planners/reviewers at sonnet ✓|✗
Savings: ~{tokens_saved} tokens{" (recycled {recycled} → upgraded {agent} {from}→{to})" if upgrade_pass_fired}
Mode: {shadow|enforce}
```

#### Calibration emit

After all Stage 2 agents complete (in Step 2.3 or synthesis), emit calibration data:

```
For each tier-adjusted agent (where adjusted_model != original_model OR mode == "shadow"):
    Log: [cmd-calibration] agent={name} score={score} original={orig} adjusted={adj}
         findings={count} max_severity={P0|P1|P2|P3|none} downgraded={true|false}
```

This structured log line enables future analysis: `grep cmd-calibration <logs> | jq` to build the calibration dataset.

#### Escalation advisory

After reading each completed agent's findings (Step 2.3):

```
if agent was tier-adjusted AND agent's max_finding_severity in (P0, P1):
    Log: [tier-escalation] {agent} was downgraded {orig}→{adj} but returned {severity} finding
         — candidate for tier escalation in future runs
```

#### Agent tier metadata

Agents dispatched via cross-model dispatch include `tier: {model}` in their output frontmatter, enabling downstream analysis of per-tier finding quality.

If `cmd_enabled == "false"`:
Launch Stage 2 agents with `run_in_background: true` using models from Step 2.0.5 map (existing behavior, unchanged).
