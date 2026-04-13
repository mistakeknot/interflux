---
artifact_type: reflection
bead: sylveste-fyo3.3
stage: reflect
category: configuration
tags: [interflux, cross-model, safety-floors, dispatch]
---
# Cross-Model Dispatch Enforce Activation — Reflection

## What changed

Switched `cross_model_dispatch.mode` from `shadow` to `enforce` in budget.yaml. Updated spec doc. Fixed stale agent-role table in the spec. Added 13-test integration suite verifying safety floors, config consistency, and dispatch eligibility.

## Key learnings

### Safety floors are convention-enforced, not compile-time verified
The dispatch algorithm lives in expansion.md as LLM-interpreted instructions. `_routing_apply_safety_floor` is called at multiple points via inline comments — "IMPORTANT: reapply safety floor" — but there is no static analyzer that guarantees the floor is applied. The defense is layered: floor applied 4 times in the algorithm, plus a pool-level quality assertion as a 5th catch. This is acceptable but should be noted as a residual risk for any future algorithm changes.

### Enforce mode with zero qualified models is a safe no-op
With all models at `candidate` status, enforce mode produces the same behavior as shadow mode — tier adjustments only affect Claude haiku/sonnet/opus selection, and the non-Claude dispatch path is not triggered. This makes the activation risk-free as a configuration change.

### Spec documents drift from config
The agent-role table in cross-model-dispatch.md was wrong on 4 agents (fd-decisions, fd-people, fd-performance, fd-game-design). The authoritative source is agent-roles.yaml, not the spec. Added a test that cross-checks the spec against config to catch future drift.
