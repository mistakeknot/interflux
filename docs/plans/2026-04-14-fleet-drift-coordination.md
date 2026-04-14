---
artifact_type: plan
bead: sylveste-fyo3.5
stage: design
requirements:
  - F1: Drift sampling orchestrator
  - F2: Integration test
---
# Fleet-Wide Drift Coordination — Plan

**Bead:** sylveste-fyo3.5
**Goal:** Wire `fluxbench-drift.sh --fleet-check` to automated sampling and fleet-wide aggregation.
**Tech Stack:** Bash, YAML, JSON, bats

---

## Task 1: Drift Sampling Orchestrator [F1]

**Files:**
- Create: `scripts/fluxbench-drift-sample.sh`

**The script:**

```bash
#!/usr/bin/env bash
# fluxbench-drift-sample.sh — periodic drift sampling orchestrator
# Usage: fluxbench-drift-sample.sh [--force]
#
# Called after reviews complete. Maintains a counter and samples at 1-in-N.
# When sampling: checks each qualified model's latest scores against its baseline.
# On drift: escalates to --fleet-check for correlated drift detection.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/../config/flux-drive"
DATA_DIR="${SCRIPT_DIR}/../data"
MODEL_REGISTRY="${MODEL_REGISTRY:-${CONFIG_DIR}/model-registry.yaml}"
RESULTS_JSONL="${FLUXBENCH_RESULTS_JSONL:-${DATA_DIR}/fluxbench-results.jsonl}"
COUNTER_FILE="${DATA_DIR}/drift-sample-counter"

force=false
[[ "${1:-}" == "--force" ]] && force=true

# Require yq for registry reads
command -v yq >/dev/null 2>&1 || { echo "Error: yq required" >&2; exit 1; }
[[ -f "$MODEL_REGISTRY" ]] || { echo "Error: model registry not found: $MODEL_REGISTRY" >&2; exit 1; }
```

**Sampling logic:**

```bash
# Read config
sample_rate=$(yq -r '.fluxbench.sample_rate // 10' "$MODEL_REGISTRY")
max_sample_gap=$(yq -r '.fluxbench.max_sample_gap // 20' "$MODEL_REGISTRY")

# Atomic counter management
mkdir -p "$DATA_DIR"
_read_counter() {
  [[ -f "$COUNTER_FILE" ]] && cat "$COUNTER_FILE" || echo "0"
}
_write_counter() {
  local tmp="${COUNTER_FILE}.tmp"
  echo "$1" > "$tmp"
  mv "$tmp" "$COUNTER_FILE"
}

current=$(_read_counter)

# Decision: should we sample?
should_sample=false
if $force; then
  should_sample=true
elif [[ "$current" -ge "$sample_rate" ]]; then
  should_sample=true
elif [[ "$current" -ge "$max_sample_gap" ]]; then
  should_sample=true
  echo "Max sample gap ($max_sample_gap) exceeded — forcing drift check" >&2
fi

if ! $should_sample; then
  # Increment counter and exit
  _write_counter $((current + 1))
  echo '{"action":"skipped","counter":'$((current + 1))',"sample_rate":'$sample_rate'}'
  exit 0
fi
```

**Drift check loop:**

```bash
# Reset counter
_write_counter 0

# Find qualified models
export _FB_REGISTRY_PATH="$MODEL_REGISTRY"
qualified_slugs=$(python3 -c "
import yaml, os
with open(os.environ['_FB_REGISTRY_PATH']) as f:
    reg = yaml.safe_load(f) or {}
models = reg.get('models', {}) or {}
for slug, m in models.items():
    if isinstance(m, dict) and m.get('status') in ('qualified', 'auto-qualified'):
        if m.get('qualified_baseline') is not None:
            print(slug)
" 2>/dev/null) || qualified_slugs=""

if [[ -z "$qualified_slugs" ]]; then
  echo '{"action":"no_qualified_models","counter":0}'
  exit 0
fi

# For each qualified model: build shadow result from latest JSONL scores
drift_detected_models=()
results=()

while IFS= read -r slug; do
  [[ -z "$slug" ]] && continue
  
  # Get latest JSONL entry for this model
  if [[ ! -f "$RESULTS_JSONL" ]]; then
    continue
  fi
  
  export _FB_SLUG="$slug"
  shadow_file=$(mktemp)
  python3 -c "
import json, os, sys

slug = os.environ['_FB_SLUG']
results_path = os.environ['RESULTS_JSONL']

with open(results_path) as f:
    lines = [json.loads(l) for l in f if l.strip()]

model_runs = [r for r in lines if r.get('model_slug') == slug]
if not model_runs:
    json.dump({'metrics': {}}, sys.stdout)
    sys.exit(0)

# Use the latest run's metrics as the shadow result
latest = model_runs[-1]
json.dump({'metrics': latest.get('metrics', {})}, sys.stdout)
" > "$shadow_file" 2>/dev/null || { rm -f "$shadow_file"; continue; }
  
  # Run drift check
  drift_result=$(bash "${SCRIPT_DIR}/fluxbench-drift.sh" "$slug" "$shadow_file" 2>/dev/null) || { rm -f "$shadow_file"; continue; }
  rm -f "$shadow_file"
  
  verdict=$(echo "$drift_result" | jq -r '.verdict // "error"')
  
  if [[ "$verdict" == "drift_detected" ]]; then
    drift_detected_models+=("$slug")
  fi
  
  results+=("$drift_result")
done <<< "$qualified_slugs"

# Fleet-check: if any individual drift detected, re-run with --fleet-check
fleet_verdict="no_drift"
if [[ ${#drift_detected_models[@]} -gt 0 ]]; then
  # Pick the first drifted model and re-run with --fleet-check
  first_drifted="${drift_detected_models[0]}"
  
  # Build shadow result for fleet check
  shadow_file=$(mktemp)
  export _FB_SLUG="$first_drifted"
  python3 -c "
import json, os, sys
slug = os.environ['_FB_SLUG']
results_path = os.environ['RESULTS_JSONL']
with open(results_path) as f:
    lines = [json.loads(l) for l in f if l.strip()]
model_runs = [r for r in lines if r.get('model_slug') == slug]
latest = model_runs[-1] if model_runs else {}
json.dump({'metrics': latest.get('metrics', {})}, sys.stdout)
" > "$shadow_file" 2>/dev/null
  
  fleet_result=$(bash "${SCRIPT_DIR}/fluxbench-drift.sh" "$first_drifted" "$shadow_file" --fleet-check 2>/dev/null) || fleet_result=""
  rm -f "$shadow_file"
  
  if [[ -n "$fleet_result" ]]; then
    fleet_verdict=$(echo "$fleet_result" | jq -r '.verdict // "error"')
  fi
  
  # Emit advisory
  if [[ "$fleet_verdict" == "baseline_shift_suspected" ]]; then
    echo "[fluxbench] BASELINE SHIFT SUSPECTED — ${#drift_detected_models[@]} model(s) drifting simultaneously. Review before demoting." >&2
  else
    for slug in "${drift_detected_models[@]}"; do
      echo "[fluxbench] DRIFT DETECTED: $slug — model may need requalification" >&2
    done
  fi
fi

# Output summary
jq -n \
  --arg action "sampled" \
  --argjson models_checked "$(echo "$qualified_slugs" | wc -l | tr -d ' ')" \
  --argjson drift_count "${#drift_detected_models[@]}" \
  --arg fleet_verdict "$fleet_verdict" \
  --argjson drifted "$(printf '%s\n' "${drift_detected_models[@]}" | jq -R . | jq -s .)" \
  '{action:$action, models_checked:$models_checked, drift_count:$drift_count, fleet_verdict:$fleet_verdict, drifted_models:$drifted}'
```

**Key design decisions:**
- Counter file at `data/drift-sample-counter` — atomic writes via tmp+mv
- Shadow result is derived from latest JSONL scores (no expensive re-runs)
- Fleet-check only triggered when individual drift detected (not on every sample)
- Advisory messages to stderr (non-blocking)
- `--force` flag bypasses counter for manual/testing use

---

## Task 2: Integration Test [F2]

**Files:**
- Create: `tests/test_fluxbench_drift_sample.bats`

Tests to write:
1. `drift-sample.sh increments counter and skips when below sample_rate`
2. `drift-sample.sh triggers check when counter reaches sample_rate`
3. `drift-sample.sh forces check on max_sample_gap`
4. `drift-sample.sh --force bypasses counter`
5. `drift-sample.sh reports no_qualified_models when none qualified`
6. `drift-sample.sh detects drift and invokes fleet-check`
7. `drift-sample.sh counter file uses atomic writes`

Setup: mock registry with a qualified model + qualified_baseline, mock JSONL with matching scores. For drift test: JSONL with degraded scores.

---

## Task Dependencies

```
Task 1 (orchestrator) ──▶ Task 2 (integration test)
```

<verify>
- run: `cd interverse/interflux && bats tests/test_fluxbench_drift_sample.bats`
  expect: exit 0
- run: `bash interverse/interflux/scripts/fluxbench-drift-sample.sh --force 2>/dev/null | jq -r '.action'`
  expect: contains "sampled" or "no_qualified_models"
</verify>
