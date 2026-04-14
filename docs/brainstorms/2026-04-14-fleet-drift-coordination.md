---
artifact_type: brainstorm
bead: sylveste-fyo3.5
stage: brainstorm
---
# Fleet-Wide Drift Coordination

## Context

`fluxbench-drift.sh` has per-model drift detection (compare against `qualified_baseline`) and `--fleet-check` correlated drift detection (>=50% simultaneous drift = baseline shift). But nothing invokes it. There's no sampling trigger, no periodic aggregation, no alerting.

## What Exists

- `fluxbench-drift.sh <model-slug> <shadow-result.json> [--fleet-check]` — fully implemented
- `model-registry.yaml` config: `sample_rate: 10` (1-in-10), `max_sample_gap: 20`
- Session-start hook at `hooks/session-start.sh` — already has FluxBench awareness section
- No shadow result generation pipeline — drift.sh needs a `shadow-result.json` as input

## The Missing Piece

The gap is the **orchestration script** that:
1. Decides whether this review should include a drift sample (1-in-N counter)
2. After a flux-drive review completes, captures the review's findings as a shadow result
3. Feeds the shadow result to `fluxbench-drift.sh` for each qualified model
4. When drift is detected, runs `--fleet-check` to distinguish individual drift from baseline shift
5. Emits an advisory to stderr (not blocking — drift is informational)

## Design Decisions

### Where to trigger: post-review hook, not SessionStart
SessionStart is too early — there's no review output yet. The right trigger point is AFTER a flux-drive review completes. The expansion phase in flux-drive already has a post-dispatch section. A new script `fluxbench-drift-sample.sh` can be called from the sprint orchestrator after quality gates, or from a post-review hook.

### Shadow result format
`drift.sh` expects `{"metrics": {"fluxbench-finding-recall": 0.75, ...}}`. In a real drift check, the "shadow" is a parallel run of the model against the same review target. For now, we can derive a lightweight proxy: compare the model's findings count and severity distribution against its baseline. Full shadow runs require re-invoking the model on the same document — that's expensive and deferred to a future enhancement.

### Sampling counter
Use a counter file at `data/drift-sample-counter` (not model-registry.yaml — avoid hot-path registry writes). Increment per review, reset to 0 when a sample is taken.

### Fleet-check aggregation
Run `--fleet-check` only when individual drift is detected. This is already implemented in drift.sh — we just need to pass the flag.

## Scope

1. **`fluxbench-drift-sample.sh`** — orchestrator that reads sample_rate, checks counter, invokes drift.sh for each qualified model, handles fleet-check
2. **Counter file management** — atomic increment/reset
3. **Integration test** — verify sampling cadence, drift detection, fleet-check escalation
4. **Wire to quality gates** — call drift-sample after quality gates complete (optional advisory)

## Non-Scope

- Full shadow re-runs (expensive, deferred)
- Automatic remediation on drift (human decision)
- Dashboard/UI for drift status
