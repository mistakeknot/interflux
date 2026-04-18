# Budget-Aware Agent Selection (Step 1.2c)

Detailed algorithm for the budget cut applied after scoring and stage assignment in
`SKILL.md` Step 1.2c. SKILL.md carries only the summary — this file carries the
full algorithm, cost estimator contract, and exempt-agent policy.

## Step 1.2c.1: Load budget config

Read `${CLAUDE_PLUGIN_ROOT}/config/flux-drive/budget.yaml`. Look up the budget for
the current `INPUT_TYPE`:

- `file` → use the `Document Profile → Type` value (plan, brainstorm, prd, spec, other)
- `diff` with < 500 lines → `diff-small`
- `diff` with >= 500 lines → `diff-large`
- `directory` → `repo`

If a project-level override exists at `{PROJECT_ROOT}/.claude/flux-drive-budget.yaml`,
use that instead.

**Sprint budget override:** If `FLUX_BUDGET_REMAINING` env var is set and non-zero,
apply: `effective_budget = min(yaml_budget, FLUX_BUDGET_REMAINING)`. This allows
sprint-level budget constraints to cap flux-drive dispatch. Note in triage summary:
`[sprint-constrained]` when the sprint budget is tighter.

Store as `BUDGET_TOTAL`.

## Step 1.2c.2: Estimate per-agent costs

Run the cost estimator:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/estimate-costs.sh --model {current_model} [--slicing if slicing active]
```

For each selected agent, look up its estimate:

1. If `estimates[agent_name]` exists (from interstat, >= 3 runs): use `est_billing`
   when `cost_basis: billing` (default), else `est_tokens`. Note
   `source: interstat (N runs)`.
2. Else: classify agent (review/cognitive/research/oracle/generated) and use
   `defaults[type]`. Note `source: default`.
3. If slicing is active AND the agent is domain-specific (NOT fd-architecture or
   fd-quality, which always review full content): multiply the estimate by
   `slicing_multiplier` (default `0.5`).

## Step 1.2c.3: Apply the budget cut

The budget cuts Stage 2 first. Stage 1 agents are always selected (protected).
After Stage 1 is fully allocated, add Stage 2 agents by score until the budget is
exceeded:

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

`min_agents` comes from `budget.yaml` (default `2`). Stage 1 always has at least
`min_agents`.

**Stage interaction:** If Stage 1 alone exceeds the budget, all Stage 1 agents
still launch (stage boundaries override budget). Stage 2 agents are deferred by
default when the budget is tight. The expansion decision (Step 2.2b) still offers
the user the option to override.

**Exempt agents:** `exempt_agents` in `budget.yaml` (fd-safety, fd-correctness) are
never deferred by budget cuts or AgentDropout. They always run regardless of
budget constraints or redundancy signals.

**No-data graceful degradation:** If the interstat DB doesn't exist or returns no
data, use defaults for ALL agents. Log: `Using default cost estimates (no
interstat data).` Do NOT skip budget enforcement — defaults provide reasonable
bounds.

## Triage table output

After applying the cut, present the triage table with budget context:

```
Agent | Score | Stage | Est. Tokens | Source | Reason | Action

Budget: {cumulative_selected}K / {BUDGET_TOTAL/1000}K ({percentage}%) | Deferred: {N} agents ({deferred_total}K est.)
```

Actions are `Selected` or `Deferred (budget)`. Exempt agents never appear as
deferred even when over budget.

## See also

- `config/flux-drive/budget.yaml` — per-INPUT_TYPE budget defaults and
  `exempt_agents`
- `scripts/estimate-costs.sh` — per-agent cost estimator (interstat-backed)
- `SKILL.md` Step 1.2c — the summary that points here
