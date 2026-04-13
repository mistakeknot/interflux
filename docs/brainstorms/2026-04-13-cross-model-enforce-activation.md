---
artifact_type: brainstorm
bead: sylveste-fyo3.3
stage: brainstorm
---
# Cross-Model Dispatch: Shadow → Enforce Activation

## Context

FluxBench scoring engine is hardened (sylveste-1n8u). Dependencies fyo3.1 (real qualify), fyo3.2 (populated registry), fyo3.4 (OpenRouter) are all closed. The cross-model dispatch algorithm in expansion.md is implemented and running in shadow mode. Time to activate enforce mode.

## Current State

- `budget.yaml` line 71: `mode: shadow` — logs tier adjustments without applying
- Shadow mode emits `[shadow-proxy]` calibration data (expansion.md § 2.2c lines 291-303)
- Safety floors enforced in agent-roles.yaml: fd-safety, fd-correctness locked to sonnet min_model
- Checker-tier agents (fd-perception, fd-resilience, fd-decisions, fd-people) are candidates for non-Claude routing
- model-registry.yaml has qualified models from discovery runs

## What Needs to Happen

1. **Config flip:** `mode: shadow` → `mode: enforce` in budget.yaml, set `enforce_since` timestamp
2. **Safety floor verification:** Confirm expansion.md phase logic reads `min_model` from agent-roles.yaml and clamps *after* tier adjustment. Walk the algorithm in expansion.md § 2.2c to verify the floor is applied post-adjustment, not pre.
3. **Integration test:** Verify that under enforce mode:
   - Checker-tier agents (fd-perception etc.) CAN be routed to a qualified non-Claude model
   - Safety agents (fd-safety, fd-correctness) ALWAYS stay on Sonnet+ regardless of budget pressure
   - The downgrade cap (max 50%) is enforced
4. **Spec update:** Change cross-model-dispatch.md status line from "shadow mode" to "enforce mode"

## Risks

- **False positive safety floor bypass:** If the algorithm applies the floor before the adjustment, a subsequent downgrade could bypass it. Need to verify ordering.
- **Model availability:** If the qualified non-Claude model becomes unavailable, the dispatch should fall back gracefully. Expansion.md should handle this (check).
- **Calibration data format change:** Shadow emits `[shadow-proxy]`, enforce emits `[cmd-calibration]`. Downstream consumers (if any) need to handle both tags.

## Non-Scope

- Not changing the algorithm itself — just switching the mode
- Not adding new models to the registry
- Not modifying safety floor definitions
