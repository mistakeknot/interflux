---
artifact_type: reflection
bead: sylveste-fyo3.5
stage: reflect
category: monitoring
tags: [fluxbench, drift, fleet, sampling]
---
# Fleet-Wide Drift Coordination — Reflection

## What changed

Created `fluxbench-drift-sample.sh` — a sampling orchestrator that wraps `fluxbench-drift.sh` with a 1-in-N counter, max gap enforcement, and fleet-check escalation on correlated drift. Added 8-test integration suite.

## Key learnings

### Shadow results from JSONL are a pragmatic proxy
Full shadow re-runs (invoking a model against the same document) are expensive. Using the latest JSONL scores as a proxy shadow result works for drift detection because the baseline comparison is the same: are the metrics degrading? The proxy doesn't catch model-specific behavioral changes that don't show in aggregate scores, but it's a good enough first pass.

### Counter files need the same atomic discipline as registries
The counter file uses the same tmp+mv pattern as all other FluxBench state files. Even though a corrupted counter only means a missed sample (not data loss), the discipline prevents subtle bugs where concurrent sessions both read the same counter value and both increment to the same number, effectively halving the sample rate.

### Advisory-only scripts are safe to ship without heavy review
This script never modifies the model registry — drift.sh does the writes, and only when drift is detected. The orchestrator is purely read + invoke + report. This pattern (advisory wrapper around a write-capable script) reduces the review burden significantly.
