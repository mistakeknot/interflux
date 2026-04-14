---
artifact_type: prd
bead: sylveste-fyo3.5
stage: strategy
---
# Fleet-Wide Drift Coordination — PRD

## Problem

Drift detection exists but is never invoked. `fluxbench-drift.sh` can detect per-model quality regression and correlated fleet-wide baseline shifts, but there is no trigger, no sampling, and no alerting. If a model provider degrades quality, we won't notice until manual investigation.

## Solution

Build `fluxbench-drift-sample.sh` — a lightweight orchestrator that samples reviews at a configurable rate (1-in-N), feeds findings to drift.sh for each qualified model, and emits advisory alerts on drift or baseline shift.

## Features

### F1: Drift sampling orchestrator (`fluxbench-drift-sample.sh`)
- Read `sample_rate` and `max_sample_gap` from model-registry.yaml
- Maintain a counter file (`data/drift-sample-counter`) — atomic increment per invocation
- When counter reaches sample_rate (or max_sample_gap exceeded), trigger drift checks
- For each qualified model: generate a proxy shadow result from recent JSONL scores, invoke `fluxbench-drift.sh`
- On any individual drift: re-run with `--fleet-check` for correlated drift detection
- Output: JSON summary to stdout, advisory messages to stderr

### F2: Integration test
- Verify sampling cadence (N calls → 1 sample)
- Verify max_sample_gap forces a sample
- Verify drift detection flows through to fleet-check
- Verify baseline_shift_suspected verdict when >=50% models drift

## Success Criteria

- `fluxbench-drift-sample.sh` runs without error given a populated registry
- Counter file increments correctly with atomic writes
- Fleet-check is invoked exactly when individual drift is detected
- No regression in existing FluxBench tests (49/49 pass)
