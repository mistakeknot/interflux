# Extension: Cross-Model Dispatch

**Status:** Implemented (interflux v0.2.56+), enforce mode (activated 2026-04-13)
**Reference:** `phases/expansion.md § 2.2c`, `config/flux-drive/budget.yaml → cross_model_dispatch`, `config/flux-drive/agent-roles.yaml`

## Summary

Routes Stage 2 / expansion pool agents to different model tiers based on expansion score, domain complexity, and budget pressure. Safety-critical agents (fd-safety, fd-correctness) have enforced minimum tiers.

## Algorithm

1. **Budget pressure**: `1.0 - (effective_budget / stage2_cost_estimates)`. Labels: low (<0.2), medium (0.2-0.5), high (>0.5).
2. **Tier adjustment**: Per agent based on expansion score (1-3), domain_complexity (low/medium/high), and pressure label.
3. **Domain intersection validation**: Non-adjacent agents capped at haiku tier.
4. **Downgrade cap**: Max 50% of candidates can be downgraded.
5. **Upgrade pass**: Savings from downgrades recycled to upgrade highest-scored score=2 agent.
6. **Pool quality assertion**: At least one planner/reviewer at sonnet tier.
7. **Safety floor**: fd-safety, fd-correctness never below sonnet (from `agent-roles.yaml → min_model`).

## Modes

- **shadow** (default): Log adjustments, dispatch at original models. Emit `[shadow-proxy]` calibration data.
- **enforce**: Apply adjusted models. Emit `[cmd-calibration]` data for future tuning.

## Agent Roles

Defined in `agent-roles.yaml`:

| Role | Tier | Agents |
|------|------|--------|
| planner | opus | fd-architecture, fd-systems |
| reviewer | sonnet | fd-correctness, fd-quality, fd-safety |
| editor | sonnet | fd-performance, fd-user-product, fd-game-design |
| checker | haiku | fd-perception, fd-resilience, fd-decisions, fd-people |

## Model Discovery (interrank/AgMoDB Integration)

When interrank MCP is available, interflux can automatically discover Pareto-efficient models for each agent tier:

1. **Query**: `recommend_model` with per-tier task descriptions (checker, analytical, judgment) and budget filter
2. **Pareto frontier**: `cost_leaderboard` for coding and agentic domains — models with best benchmark-per-dollar
3. **Registry**: New candidates written to `model-registry.yaml` with `status: candidate`
4. **Qualification**: Shadow runs compare candidate output against Claude baseline (format compliance, finding recall, severity accuracy)
5. **Promotion**: Qualified models enter `status: active` and become eligible for dispatch

This creates a continuous improvement loop: AgMoDB tracks new model releases → interrank scores them → discover-models.sh surfaces candidates → qualification validates them → cross-model dispatch routes to them.

**Reference:** `config/flux-drive/model-registry.yaml`, `scripts/discover-models.sh`, `references/progressive-enhancements.md § Step 1.0.6`

## Conformance

Optional extension. An implementation without cross-model dispatch uses a single model for all agents.
