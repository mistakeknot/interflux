# Extension: Budget System

**Status:** Implemented (interflux v0.2.45+)
**Reference:** `config/flux-drive/budget.yaml`, `scripts/estimate-costs.sh`, `SKILL-compact.md § 1.2c`

## Summary

Token budget enforcement prevents unbounded cost growth. Budgets are defined per input type, estimated per agent from historical data, and enforced via soft caps with override options.

## Budget Lifecycle

1. **Load** (Step 1.2c.1): Read budget for input type from `budget.yaml`. Sprint override via `FLUX_BUDGET_REMAINING` env var.
2. **Estimate** (Step 1.2c.2): Per-agent costs from interstat (≥3 runs) → fleet registry → defaults. Slicing multiplier (0.5x) for sliced agents.
3. **Cut** (Step 1.2c.3): Stage 1 always protected. Stage 2 agents added by score until budget exceeded. Exempt agents (fd-safety, fd-correctness) never deferred.
4. **Reaction cap** (Step 2.5.3a): Reaction round capped at `reaction_budget.fraction` (25%) of total.
5. **Report** (Step 3.4b): Estimated vs actual comparison with per-agent delta percentages.

## Cost Basis

Two token metrics tracked (see `agents/measurement.md`):
- **Billing tokens** (`input + output`): Used for budget enforcement (`cost_basis: billing`)
- **Total tokens** (`input + output + cache_read + cache_creation`): Used for context window decisions

Cache reads are free for billing but consume context. The default `cost_basis: billing` prevents over-counting from cache hits.

## Configuration

```yaml
budgets:
  plan: 150000
  diff-small: 60000
  diff-large: 200000
  repo: 300000
agent_defaults:
  review: 40000
  cognitive: 35000
  research: 15000
  reaction: 15000
enforcement: soft        # soft = warn | hard = block
cost_basis: billing      # billing | total
```

## Conformance

Optional extension. An implementation without budget enforcement dispatches all selected agents unconditionally.
