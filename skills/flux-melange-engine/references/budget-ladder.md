# Reference: Budget Ladder & Per-Directive Fan-Out

flux-melange spends agents over *many* rounds, so an unbounded loop is the primary cost risk. The budget is a single accumulator, decremented by **measured** cost each round, and it is one of the three hard halts.

## Initial budget

`phases/charter.md` computes the starting budget:

1. Read `${CLAUDE_PLUGIN_ROOT}/config/flux-melange/defaults.yaml` (`budget:` block) and merge any `{PROJECT_ROOT}/.claude/flux-melange.yaml` override.
2. If `--budget=N` is passed, it wins (N = total agent slots across the whole run).
3. If `--budget=auto`, derive a slot count in two steps (the estimator gives the *per-agent* cost; `budget.yaml` gives the *total* token budget — they live in different files):

   a. **Per-agent token estimate** from the estimator:
      ```bash
      bash ${CLAUDE_PLUGIN_ROOT}/scripts/estimate-costs.sh --model {QUALITY's design model}
      ```
      It returns `{"estimates":{...}, "defaults":{review,cognitive,research,oracle,generated}, "slicing_multiplier"}`. Use `defaults.generated` (fused/probe lenses are generated agents) as `per_agent_estimate`. **Cold-start note:** if `jq`/`sqlite3`/interstat are absent the script prints a warning and returns empty `estimates{}` with the hardcoded `defaults` — that is fine, `defaults.generated` (≈40000) is exactly the value auto mode needs; do not treat the empty `estimates` as a failure.

   b. **Total token budget** from `${CLAUDE_PLUGIN_ROOT}/config/flux-drive/budget.yaml` (the `budgets.*` map), keyed by the melange target's `INPUT_TYPE`:
      | melange INPUT_TYPE | `budgets.*` key |
      |--------------------|-----------------|
      | `directory` | `repo` |
      | `file` (a doc/plan/prd) | `plan` |
      | `file` (code) or `diff` < 500 lines | `diff-small` |
      | `diff` ≥ 500 lines | `diff-large` |
      | `text` (inline) | `plan` |
      Because melange *loops*, multiply the single-pass `budgets.*` value by `max_rounds` to get `token_budget` (a loop spends roughly per-round what a single review spends).

   Then `total_slots = floor(token_budget / per_agent_estimate)`, clamped to the **hard cap of 30 agents** regardless of config. If `budget.yaml` cannot be read, fall back to the `defaults.yaml` `budget:` block's numeric value (already a slot count), else the 30-cap.
4. Honor `FLUX_BUDGET_REMAINING` exactly as flux-drive does: `effective = min(derived, FLUX_BUDGET_REMAINING)` when that env var is set and non-zero (so a sprint can cap a melange run). Tag the plan `[sprint-constrained]` when it binds.

Write the result to `melange-state.json:budget = { total, remaining: total, round_cost_floor }`. `round_cost_floor` is the minimum slots a useful round needs (default 3); the loop halts on BUDGET when `remaining < round_cost_floor`.

## Per-round decrement

After each round, `phases/score.md` decrements `budget.remaining` by the **actual** number of agents dispatched that round (seed, probes, fusions, verifiers, adjudicators). Never decrement by an estimate — measured cost is what makes the BUDGET halt honest.

## Per-directive fan-out scaling

The controller's directives carry `budget_weight`s summing to ≤ 1.0. The round's agent count is:

```
round_slots = min(remaining, max_round_slots)        # max_round_slots from config, default 8
agents(directive_i) = max(1, round(budget_weight_i × round_slots))
```

- Higher-heat directives (DEEPEN on a scary cluster, FUSE on a hot pair) get proportionally more slots.
- **Floor of 1** per directive so a kept directive always runs at least once.
- **Reserve protection:** when STEER-WIDE is *active*, it gets a fixed minimum slot before proportional allocation, so a dominant DEEPEN/FUSE can't starve the one exploratory probe. When STEER-WIDE is skipped (its `novel_cluster_rate` gate fails), its weight reallocates proportionally to the survivors.

> **Open verification (documented):** budget-proportional fan-out keyed off a parsed JSON heat field is buildable on the accumulator pattern but unproven at > 2 directives. Confirm the controller splits `remaining` across directives without starving the reserved STEER-WIDE before trusting it on large runs.

## Verify is conditional (cost guard)

The verify phase is **not** a per-round tax. It fires only on findings with `novelty ≥ 2 OR risk.product ≥ 9`, and runs on a **cheap model**. This de-defaults the expensive path the design's judge flagged — a maximize-until-dry goal with verify-everything would compound cost every round.

## Quality → model routing

| Step | economy | balanced | max |
|------|---------|----------|-----|
| Seed design (adjacent / distant) | sonnet | sonnet / **opus** | opus |
| Probe reviews (lens application) | sonnet | sonnet | opus |
| Fused-lens design | sonnet | **opus** | opus |
| Assayer (novelty/risk) | sonnet | sonnet | opus |
| Taste annotation | — (skipped) | **opus** | opus |
| Verify | haiku/sonnet (cheap) | sonnet (cheap) | sonnet |
| Synthesis (eye of distance) | sonnet | **opus** | opus |

Rationale mirrors flux-review's: creative steps (fused-lens design, synthesis) and deep-reasoning steps need Opus; lens *application* and routine scoring are Sonnet-adequate. Taste is Opus-only by construction (annotation, not axis).
