---
artifact_type: prd
bead: sylveste-fyo3.3
stage: strategy
---
# Cross-Model Dispatch Enforce Activation — PRD

## Problem

Cross-model dispatch runs in shadow mode — it computes tier adjustments but doesn't apply them. Models qualified by FluxBench are in the registry but never actually dispatched. The qualification pipeline (sylveste-1n8u) and discovery pipeline (fyo3.1, fyo3.2) are complete. Shadow mode was the right staging strategy; now it's time to enforce.

## Solution

Switch `cross_model_dispatch.mode` from `shadow` to `enforce` in budget.yaml. Verify safety floors hold under enforce mode. Add integration test proving checker-tier agents route to qualified non-Claude models while safety agents stay on Sonnet+.

## Features

### F1: Config activation
- Change `mode: shadow` → `mode: enforce` in budget.yaml
- Set `enforce_since` to current ISO timestamp
- Update spec doc status

### F2: Safety floor verification
- Walk the expansion.md algorithm to confirm floor clamping happens after tier adjustment
- Verify agent-roles.yaml `min_model` is read and applied in the dispatch path
- Check fallback behavior when a dispatched model is unavailable

### F3: Integration test
- Test that checker-tier agents (fd-perception, fd-resilience, fd-decisions, fd-people) can be routed to a non-Claude model when one is qualified
- Test that fd-safety and fd-correctness always stay on Sonnet+ regardless of pressure
- Test the 50% downgrade cap

## Success Criteria

- `mode: enforce` in budget.yaml
- Integration test passes showing heterogeneous routing
- No regression in existing FluxBench test suite (36/36 pass)
- Safety agents never downgraded below Sonnet in any test scenario

## Non-Goals

- Changing the dispatch algorithm itself
- Adding new models to the registry
- Modifying safety floor definitions
