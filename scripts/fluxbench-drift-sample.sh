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
COUNTER_FILE="${DRIFT_SAMPLE_COUNTER:-${DATA_DIR}/drift-sample-counter}"

force=false
[[ "${1:-}" == "--force" ]] && force=true

# Require yq for registry reads
if ! command -v yq >/dev/null 2>&1; then
  echo "Error: yq required for drift sampling" >&2
  exit 1
fi

[[ -f "$MODEL_REGISTRY" ]] || { echo "Error: model registry not found: $MODEL_REGISTRY" >&2; exit 1; }

# --- Config ---
sample_rate=$(yq -r '.fluxbench.sample_rate // 10' "$MODEL_REGISTRY")
max_sample_gap=$(yq -r '.fluxbench.max_sample_gap // 20' "$MODEL_REGISTRY")

# --- Counter management (atomic) ---
mkdir -p "$(dirname "$COUNTER_FILE")"

_read_counter() {
  if [[ -f "$COUNTER_FILE" ]]; then
    local val
    val=$(cat "$COUNTER_FILE")
    # Validate numeric
    if [[ "$val" =~ ^[0-9]+$ ]]; then
      echo "$val"
    else
      echo "0"
    fi
  else
    echo "0"
  fi
}

_write_counter() {
  local tmp="${COUNTER_FILE}.tmp"
  echo "$1" > "$tmp"
  mv "$tmp" "$COUNTER_FILE"
}

current=$(_read_counter)

# --- Decision: should we sample? ---
should_sample=false
sample_reason=""

if $force; then
  should_sample=true
  sample_reason="forced"
elif [[ "$current" -ge "$sample_rate" ]]; then
  should_sample=true
  sample_reason="sample_rate_reached"
elif [[ "$current" -ge "$max_sample_gap" ]]; then
  should_sample=true
  sample_reason="max_gap_exceeded"
  echo "Max sample gap ($max_sample_gap) exceeded — forcing drift check" >&2
fi

if ! $should_sample; then
  _write_counter $((current + 1))
  jq -n \
    --arg action "skipped" \
    --argjson counter "$((current + 1))" \
    --argjson sample_rate "$sample_rate" \
    '{action:$action, counter:$counter, sample_rate:$sample_rate}'
  exit 0
fi

# --- Reset counter ---
_write_counter 0

# --- Find qualified models with baselines ---
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
  jq -n '{"action":"no_qualified_models","counter":0}'
  exit 0
fi

models_checked=0
drift_detected_models=()

# --- Drift check loop ---
while IFS= read -r slug; do
  [[ -z "$slug" ]] && continue
  models_checked=$((models_checked + 1))

  # Get latest JSONL entry for this model
  if [[ ! -f "$RESULTS_JSONL" ]]; then
    continue
  fi

  shadow_file=$(mktemp)

  export _FB_SLUG="$slug"
  export _FB_RESULTS="$RESULTS_JSONL"
  python3 -c "
import json, os, sys

slug = os.environ['_FB_SLUG']
results_path = os.environ['_FB_RESULTS']

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

  # Run drift check (without --fleet-check first). Let drift.sh stderr through
  # so its lock-timeout warnings surface in the sampler's log.
  drift_result=$(bash "${SCRIPT_DIR}/fluxbench-drift.sh" "$slug" "$shadow_file") || { rm -f "$shadow_file"; continue; }
  rm -f "$shadow_file"

  verdict=$(echo "$drift_result" | jq -r '.verdict // "error"')

  # drift.sh returns "skipped_timeout" when it cannot acquire the registry lock
  # within its own flock -w 30 budget. Log and continue (advisory operation).
  if [[ "$verdict" == "skipped_timeout" ]]; then
    echo "[fluxbench-drift-sample] drift check skipped for $slug (registry lock contention)" >&2
    continue
  fi

  if [[ "$verdict" == "drift_detected" ]]; then
    drift_detected_models+=("$slug")
  fi
done <<< "$qualified_slugs"

# --- Fleet-check: if any individual drift detected ---
fleet_verdict="no_drift"

if [[ ${#drift_detected_models[@]} -gt 0 ]]; then
  first_drifted="${drift_detected_models[0]}"

  shadow_file=$(mktemp)
  export _FB_SLUG="$first_drifted"
  export _FB_RESULTS="$RESULTS_JSONL"
  python3 -c "
import json, os, sys
slug = os.environ['_FB_SLUG']
results_path = os.environ['_FB_RESULTS']
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

  # Emit advisories
  if [[ "$fleet_verdict" == "baseline_shift_suspected" ]]; then
    echo "[fluxbench] BASELINE SHIFT SUSPECTED — ${#drift_detected_models[@]} model(s) drifting simultaneously. Review before demoting." >&2
  else
    for drifted_slug in "${drift_detected_models[@]}"; do
      echo "[fluxbench] DRIFT DETECTED: $drifted_slug — model may need requalification" >&2
    done
  fi
fi

# --- Output summary ---
drifted_json="[]"
if [[ ${#drift_detected_models[@]} -gt 0 ]]; then
  drifted_json=$(printf '%s\n' "${drift_detected_models[@]}" | jq -R . | jq -s .)
fi

jq -n \
  --arg action "sampled" \
  --arg reason "$sample_reason" \
  --argjson models_checked "$models_checked" \
  --argjson drift_count "${#drift_detected_models[@]}" \
  --arg fleet_verdict "$fleet_verdict" \
  --argjson drifted_models "$drifted_json" \
  '{action:$action, reason:$reason, models_checked:$models_checked, drift_count:$drift_count, fleet_verdict:$fleet_verdict, drifted_models:$drifted_models}'
