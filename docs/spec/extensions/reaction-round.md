# Extension: Reaction Round (Phase 2.5)

**Status:** Implemented (interflux v0.2.50+)
**Reference:** `phases/reaction.md`, `config/flux-drive/reaction.yaml`

## Summary

After Phase 2 agents complete and before synthesis, a controlled reaction round allows agents to critique each other's findings. Each agent receives peer findings (filtered by topology) and produces reactions that confirm, dispute, or extend.

## Components

| Component | Config | Description |
|-----------|--------|-------------|
| Convergence gate | `reaction.yaml → gate` | Haiku LLM or formula gate decides whether reaction adds value |
| Discourse topology | `discourse-topology.yaml` | Sparse communication — same role=full, adjacent=summary, other=none |
| Discourse fixative | `discourse-fixative.yaml` | Corrective prompt injection based on Gini/novelty metrics |
| Sycophancy detection | `reaction.yaml → sycophancy_detection` | Flags high-agreement/low-independence patterns |
| Hearsay detection | `reaction.yaml → hearsay_detection` | Discounts confirmations without independent evidence |
| Peer findings sanitization | `phases/reaction.md § 2.5.3` | Strips prompt injection from peer findings before template substitution |
| Budget cap | `budget.yaml → reaction_budget` | Limits reaction to 25% of total budget, drops lowest-score agents first |

## Protocol

1. **Gate** (Step 2.5.0): Fast-path guards (0 agents, 1 agent, 0 findings → skip). Then intercept gate or haiku LLM decides PROCEED/SKIP.
2. **Collect** (Step 2.5.2): Extract findings indexes, apply topology filtering and fixative health check.
3. **Sanitize** (Step 2.5.3): Strip XML tags, instruction overrides, shell code fences. Cap 2000 chars/agent.
4. **Budget** (Step 2.5.3a): Estimate reaction cost, drop lowest-score agents if over cap.
5. **Dispatch** (Step 2.5.4): Parallel Agent calls, model=sonnet, same subagent_type as original.
6. **Report** (Step 2.5.5): Emit interspect evidence with dispatch/completion stats.

## Conformance

Optional extension. An implementation without reaction round simply proceeds from Phase 2 to Phase 3.
