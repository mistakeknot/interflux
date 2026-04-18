#!/usr/bin/env bash
# fluxbench-drift.sh — detect model quality drift against qualified baseline
# Usage: fluxbench-drift.sh <model-slug> <shadow-result.json> [--fleet-check]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

model_slug="${1:?Usage: fluxbench-drift.sh <model-slug> <shadow-result.json> [--fleet-check]}"
shadow_result="${2:?Missing shadow-result.json}"
fleet_check=false
if [[ "${3:-}" == "--fleet-check" ]]; then
  fleet_check=true
fi

# Validate model_slug format (prevent yq injection)
if [[ ! "$model_slug" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$ ]]; then
  echo "Error: invalid model slug format: $model_slug" >&2
  exit 1
fi
_safe_slug="$model_slug"  # validated above, safe for yq interpolation

registry="${MODEL_REGISTRY:-${SCRIPT_DIR}/../config/flux-drive/model-registry.yaml}"
metrics_file="${METRICS_FILE:-${SCRIPT_DIR}/../config/flux-drive/fluxbench-metrics.yaml}"

[[ -f "$shadow_result" ]] || { echo "Error: shadow result not found: $shadow_result" >&2; exit 1; }
[[ -f "$registry" ]]      || { echo "Error: model registry not found: $registry" >&2; exit 1; }

# Require yq for registry operations
if ! command -v yq >/dev/null 2>&1; then
  echo "Error: yq is required but not found. Install with: pip install yq" >&2
  exit 1
fi

# Read drift config from registry root (root-level config, not per-model)
drift_threshold=$(yq -r '.fluxbench.drift_threshold // 0.15' "$registry")
hysteresis_band=$(yq -r '.fluxbench.hysteresis_band // 0.05' "$registry")
correlated_drift_threshold=$(yq -r '.fluxbench.correlated_drift_threshold // 0.50' "$registry")

# Build higher_is_better map from metrics config.
# Do NOT swallow yq errors here: if the metrics file is present but malformed, an empty map
# silently flips regression-direction interpretation (false_positive_rate would read as
# "higher is better", so a regression scores as an improvement). Fail loudly instead.
declare -A higher_is_better_map
if [[ -f "$metrics_file" ]]; then
  _fd_yq_err=$(mktemp)
  if ! while IFS='=' read -r metric val; do
    higher_is_better_map["$metric"]="$val"
  done < <(yq -r '
    (.core_gates // {}) as $c | ($c | keys[] | . + "=" + ($c[.].higher_is_better | tostring)),
    (.extended // {}) as $e | ($e | keys[] | . + "=" + ($e[.].higher_is_better | tostring))
  ' "$metrics_file" 2>"$_fd_yq_err"); then
    echo "fluxbench-drift: failed to parse $metrics_file — drift direction cannot be trusted" >&2
    cat "$_fd_yq_err" >&2
    rm -f "$_fd_yq_err"
    exit 1
  fi
  rm -f "$_fd_yq_err"
fi

# Extract current scores from shadow result
current_metrics=$(jq -c '.metrics // {}' "$shadow_result")

# Build higher_is_better map as key=value lines
_hib_lines=""
for k in "${!higher_is_better_map[@]}"; do _hib_lines+="${k}=${higher_is_better_map[$k]}"$'\n'; done

# All registry reads, drift computation, and registry writes under a single
# exclusive flock to prevent TOCTOU races with concurrent writers.
# Use a temp file to capture output from the flock subshell.
_drift_output_file=$(mktemp)
trap 'rm -f "$_drift_output_file"' EXIT

# flock -w 30 bounds the wait when a concurrent writer (qualify.sh, challenger.sh)
# holds the registry lock. Without the timeout, drift-sample.sh deadlocks, cascading
# into the session-start hook chain. Drift is advisory: on timeout emit a skip
# verdict at exit 0 so callers continue. Exit 3 is the in-subshell signal for
# timeout; anything else non-zero is a real registry-operation failure.
_flock_rc=0
(
  flock -w 30 -x 201 || exit 3

  # Read model's qualified baseline
  baseline_json=$(yq -o=json ".models.\"${_safe_slug}\".qualified_baseline // null" "$registry")
  if [[ "$baseline_json" == "null" || -z "$baseline_json" ]]; then
    echo "Error: no qualified_baseline for model '$_safe_slug'" >&2
    exit 1
  fi

  # Read current drift_flagged state
  drift_flagged=$(yq -r ".models.\"${_safe_slug}\".drift_flagged // false" "$registry")

  # Compare each baseline metric against current — pass data via env vars (no interpolation)
  export _FB_BASELINE_JSON="$baseline_json"
  export _FB_CURRENT_METRICS="$current_metrics"
  export _FB_DRIFT_THRESHOLD="$drift_threshold"
  export _FB_HYSTERESIS_BAND="$hysteresis_band"
  export _FB_DRIFT_FLAGGED="$drift_flagged"
  export _FB_MODEL_SLUG="$_safe_slug"
  export _FB_HIB_MAP="$_hib_lines"

  _result=$(python3 -c "
import json, sys, os

baseline = json.loads(os.environ['_FB_BASELINE_JSON'])
current = json.loads(os.environ['_FB_CURRENT_METRICS'])
drift_threshold = float(os.environ['_FB_DRIFT_THRESHOLD'])
hysteresis_band = float(os.environ['_FB_HYSTERESIS_BAND'])
drift_flagged = os.environ['_FB_DRIFT_FLAGGED'] == 'true'
model_slug = os.environ['_FB_MODEL_SLUG']

# higher_is_better map
hib_map = {}
hib_raw = os.environ.get('_FB_HIB_MAP', '')
for line in hib_raw.strip().split('\n'):
    if '=' in line:
        k, v = line.split('=', 1)
        hib_map[k.strip()] = v.strip() == 'true'

drifted_metrics = []
max_drift = 0.0
all_within_hysteresis = True

for metric, baseline_val in baseline.items():
    if baseline_val is None:
        continue
    current_val = current.get(metric)
    if current_val is None:
        continue

    higher_is_better = hib_map.get(metric, True)

    if higher_is_better:
        # Drift = baseline - current (positive means regression)
        drift = baseline_val - current_val
    else:
        # For lower-is-better, drift = current - baseline (positive means regression)
        drift = current_val - baseline_val

    abs_diff = abs(baseline_val - current_val)

    if drift > max_drift:
        max_drift = drift

    if drift > drift_threshold:
        drifted_metrics.append(metric)

    if abs_diff > hysteresis_band:
        all_within_hysteresis = False

# Determine verdict
if len(drifted_metrics) > 0:
    verdict = 'drift_detected'
elif drift_flagged and all_within_hysteresis:
    verdict = 'drift_cleared'
elif drift_flagged and not all_within_hysteresis:
    verdict = 'drift_recovering'
else:
    verdict = 'no_drift'

result = {
    'model': model_slug,
    'verdict': verdict,
    'drifted_metrics': drifted_metrics,
    'max_drift': round(max_drift, 4)
}
print(json.dumps(result))
")

  _verdict=$(echo "$_result" | jq -r '.verdict')

  # If drift detected, flag the model in registry
  if [[ "$_verdict" == "drift_detected" ]]; then
    cp "$registry" "${registry}.tmp"
    yq -i ".models.\"${_safe_slug}\".drift_flagged = true" "${registry}.tmp"
    mv "${registry}.tmp" "$registry"
  fi

  # If drift cleared, unflag the model
  if [[ "$_verdict" == "drift_cleared" ]]; then
    cp "$registry" "${registry}.tmp"
    yq -i ".models.\"${_safe_slug}\".drift_flagged = false" "${registry}.tmp"
    mv "${registry}.tmp" "$registry"
  fi

  echo "$_result" > "$_drift_output_file"
) 201>"${registry}.lock" || _flock_rc=$?

if [[ $_flock_rc -eq 3 ]]; then
  echo "fluxbench-drift: lock timeout after 30s on ${registry}.lock — emitting skip verdict" >&2
  printf '{"model":"%s","verdict":"skipped_timeout","drifted_metrics":[],"max_drift":0}\n' "$_safe_slug"
  exit 0
elif [[ $_flock_rc -ne 0 ]]; then
  echo "fluxbench-drift: registry operation failed (rc=$_flock_rc)" >&2
  exit 1
fi

result=$(cat "$_drift_output_file")
verdict=$(echo "$result" | jq -r '.verdict')

# Fleet-check: if drift detected and --fleet-check, check for correlated drift
# This reads post-write state, so it runs outside the main flock.
if [[ "$fleet_check" == "true" && "$verdict" == "drift_detected" ]]; then
  export _FB_REGISTRY_PATH="$registry"
  export _FB_CORRELATED_THRESH="$correlated_drift_threshold"
  fleet_result=$(python3 -c "
import json, sys, os

registry_path = os.environ['_FB_REGISTRY_PATH']

# Count qualified models and how many are drift-flagged
import yaml
with open(registry_path) as f:
    reg = yaml.safe_load(f)

models = reg.get('models', {}) or {}
if isinstance(models, list):
    # Handle list format
    qualified = [m for m in models if m.get('status') == 'qualified']
    flagged = [m for m in qualified if m.get('drift_flagged', False)]
else:
    qualified = [k for k, v in models.items() if isinstance(v, dict) and v.get('status') == 'qualified']
    flagged = [k for k in qualified if models[k].get('drift_flagged', False)]

total = len(qualified)
n_flagged = len(flagged)

if total == 0:
    ratio = 0.0
else:
    ratio = n_flagged / total

threshold = float(os.environ['_FB_CORRELATED_THRESH'])
baseline_shift = ratio >= threshold

print(json.dumps({'baseline_shift': baseline_shift, 'flagged': n_flagged, 'total': total, 'ratio': round(ratio, 4)}))
")

  baseline_shift=$(echo "$fleet_result" | jq -r '.baseline_shift')
  if [[ "$baseline_shift" == "true" ]]; then
    # Override verdict to baseline_shift_suspected
    result=$(echo "$result" | jq '.verdict = "baseline_shift_suspected"')
  fi
fi

echo "$result"
