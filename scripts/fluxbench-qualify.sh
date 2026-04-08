#!/usr/bin/env bash
# fluxbench-qualify.sh — run qualification suite for a candidate model
# Usage: fluxbench-qualify.sh <model-slug> [--mock] [--fixtures-dir <dir>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/../config/flux-drive"
DEFAULT_FIXTURES_DIR="${SCRIPT_DIR}/../tests/fixtures/qualification"
MODEL_REGISTRY="${MODEL_REGISTRY:-${CONFIG_DIR}/model-registry.yaml}"

# --- Argument parsing ---
model_slug=""
mock_mode=false
fixtures_dir="$DEFAULT_FIXTURES_DIR"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mock)        mock_mode=true; shift ;;
    --fixtures-dir) fixtures_dir="$2"; shift 2 ;;
    -*)            echo "Error: unknown flag $1" >&2; exit 1 ;;
    *)
      if [[ -z "$model_slug" ]]; then
        model_slug="$1"; shift
      else
        echo "Error: unexpected argument $1" >&2; exit 1
      fi
      ;;
  esac
done

[[ -n "$model_slug" ]] || { echo "Usage: fluxbench-qualify.sh <model-slug> [--mock] [--fixtures-dir <dir>]" >&2; exit 1; }

# --- Validate fixtures directory ---
[[ -d "$fixtures_dir" ]] || { echo "Error: fixtures directory not found: $fixtures_dir" >&2; exit 1; }

fixture_dirs=()
for d in "$fixtures_dir"/fixture-*/; do
  [[ -d "$d" ]] && fixture_dirs+=("$d")
done

[[ ${#fixture_dirs[@]} -gt 0 ]] || { echo "Error: no fixture-* directories found in $fixtures_dir" >&2; exit 1; }

# --- Real mode not yet supported ---
if [[ "$mock_mode" == "false" ]]; then
  echo "Error: real model dispatch not yet supported — use --mock for qualification testing" >&2
  exit 1
fi

# --- Qualification run metadata ---
timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
epoch=$(date +%s)
qual_run_id="qr-${model_slug}-${epoch}"

echo "Starting qualification run: $qual_run_id" >&2
echo "  Model: $model_slug" >&2
echo "  Fixtures: ${#fixture_dirs[@]}" >&2
echo "  Mode: $(if $mock_mode; then echo mock; else echo real; fi)" >&2

# --- Temp workspace ---
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT

# --- Run each fixture ---
total_fixtures=${#fixture_dirs[@]}
valid_outputs=0
all_results=()
overall_pass=true
failure_reasons=()

for fixture_dir in "${fixture_dirs[@]}"; do
  fixture_id=$(basename "$fixture_dir")
  ground_truth="${fixture_dir}/ground-truth.json"

  [[ -f "$ground_truth" ]] || { echo "Warning: no ground-truth.json in $fixture_dir — skipping" >&2; continue; }

  echo "  Scoring fixture: $fixture_id" >&2

  # Extract agent_type from ground-truth
  agent_type=$(jq -r '.agent_type // "unknown"' "$ground_truth")

  # In mock mode, use ground-truth as the model output (perfect run)
  if $mock_mode; then
    model_output="$ground_truth"
    valid_outputs=$((valid_outputs + 1))
  fi

  # Compute format_compliance_rate (running tally — updated after all fixtures)
  # For now, build qualification-output.json per fixture
  qual_output="${work_dir}/${fixture_id}-qual-output.json"
  result_output="${work_dir}/${fixture_id}-result.json"

  # Build qualification output JSON
  jq -n \
    --arg model_slug "$model_slug" \
    --arg qual_run_id "$qual_run_id" \
    --arg agent_type "$agent_type" \
    --arg timestamp "$timestamp" \
    --argjson findings "$(jq -c '.findings // []' "$model_output")" \
    --argjson format_compliance_rate 1.0 \
    '{
      model_slug: $model_slug,
      findings: $findings,
      format_compliance_rate: $format_compliance_rate,
      metadata: {
        qualification_run_id: $qual_run_id,
        agent_type: $agent_type,
        baseline_model: "ground-truth",
        timestamp: $timestamp
      }
    }' > "$qual_output"

  # Invoke fluxbench-score.sh — ground-truth is the baseline
  if ! bash "${SCRIPT_DIR}/fluxbench-score.sh" "$qual_output" "$ground_truth" "$result_output" 2>&1; then
    echo "  Error: scoring failed for $fixture_id" >&2
    overall_pass=false
    failure_reasons+=("$fixture_id: scoring failed")
    continue
  fi

  # Check gate results
  fixture_pass=$(jq -r '.overall_pass' "$result_output")
  if [[ "$fixture_pass" != "true" ]]; then
    overall_pass=false
    # Collect which gates failed
    failed_gates=$(jq -r '
      .gate_results | to_entries[]
      | select(.value.passed == false)
      | "\(.key)=\(.value.value) (threshold: \(.value.threshold))"
    ' "$result_output" | tr '\n' '; ')
    failure_reasons+=("$fixture_id: $failed_gates")
    echo "  FAIL: $fixture_id — $failed_gates" >&2
  else
    echo "  PASS: $fixture_id" >&2
  fi

  all_results+=("$result_output")
done

# --- Compute final format_compliance_rate ---
if [[ $total_fixtures -gt 0 ]]; then
  format_compliance_rate=$(python3 -c "print(round($valid_outputs / $total_fixtures, 4))")
else
  format_compliance_rate="0.0"
fi

echo "" >&2
echo "Qualification summary:" >&2
echo "  Format compliance rate: $format_compliance_rate" >&2
echo "  Fixtures passed: $((total_fixtures - ${#failure_reasons[@]}))/$total_fixtures" >&2

# --- Aggregate scores across all fixtures ---
if [[ ${#all_results[@]} -gt 0 ]]; then
  # Compute average metrics across all fixtures
  export _FB_FC_RATE="$format_compliance_rate"
  avg_metrics=$(python3 -c "
import json, sys, os

fc_rate = float(os.environ['_FB_FC_RATE'])
results = []
for path in sys.argv[1:]:
    with open(path) as f:
        results.append(json.load(f))

metrics = {}
for key in ['fluxbench-finding-recall', 'fluxbench-false-positive-rate',
            'fluxbench-severity-accuracy']:
    vals = [r['metrics'][key] for r in results if r['metrics'].get(key) is not None]
    if vals:
        metrics[key] = round(sum(vals) / len(vals), 4)

# Format compliance is computed separately
metrics['fluxbench-format-compliance'] = fc_rate

print(json.dumps(metrics))
" "${all_results[@]}")
fi

# --- Decide status ---
if [[ "$overall_pass" == "true" ]]; then
  new_status="auto-qualified"
  echo "  Result: QUALIFIED — promoting to $new_status" >&2
else
  new_status="candidate"
  echo "  Result: NOT QUALIFIED — remaining as $new_status" >&2
  for reason in "${failure_reasons[@]}"; do
    echo "    - $reason" >&2
  done
fi

# --- Update model-registry.yaml ---
if [[ -f "$MODEL_REGISTRY" ]]; then
  _update_registry() {
    local tmp_reg
    tmp_reg=$(mktemp)
    trap 'rm -f "$tmp_reg"' RETURN
    export _FB_TMP_REG="$tmp_reg"

    # Atomic write: read → modify in tmp → validate → mv
    cp "$MODEL_REGISTRY" "$tmp_reg"

    python3 -c "
import yaml, json, sys, os

reg_path = os.environ['_FB_TMP_REG']
slug = os.environ['_FB_SLUG']
new_status = os.environ['_FB_STATUS']
avg_json = os.environ.get('_FB_AVG_METRICS') or '{}'

with open(reg_path) as f:
    reg = yaml.safe_load(f)

if reg is None:
    reg = {}
if 'models' not in reg or reg['models'] is None:
    reg['models'] = {}
# Convert list to dict if needed
if isinstance(reg['models'], list):
    reg['models'] = {}

model = reg['models'].get(slug)
if model is None:
    model = {}
    reg['models'][slug] = model

# Update status
model['status'] = new_status

# Update fluxbench scores
metrics = json.loads(avg_json) if avg_json else {}
if metrics:
    if 'fluxbench' not in model or model['fluxbench'] is None:
        model['fluxbench'] = {}
    fb = model['fluxbench']
    fb['format_compliance'] = metrics.get('fluxbench-format-compliance')
    fb['finding_recall'] = metrics.get('fluxbench-finding-recall')
    fb['false_positive_rate'] = metrics.get('fluxbench-false-positive-rate')
    fb['severity_accuracy'] = metrics.get('fluxbench-severity-accuracy')

# Write-once contract for qualified_baseline
if new_status in ('auto-qualified', 'qualified') and metrics:
    current_baseline = model.get('qualified_baseline')
    if current_baseline is None:
        model['qualified_baseline'] = {
            'fluxbench-format-compliance': metrics.get('fluxbench-format-compliance'),
            'fluxbench-finding-recall': metrics.get('fluxbench-finding-recall'),
            'fluxbench-false-positive-rate': metrics.get('fluxbench-false-positive-rate'),
            'fluxbench-severity-accuracy': metrics.get('fluxbench-severity-accuracy'),
        }
    else:
        print('  qualified_baseline already set — preserving existing baseline', file=sys.stderr)

with open(reg_path, 'w') as f:
    yaml.dump(reg, f, default_flow_style=False, sort_keys=False)
" 2>&1

    # Validate before swapping
    python3 -c "import yaml; yaml.safe_load(open('$tmp_reg'))" || { echo "Error: registry validation failed" >&2; return 1; }
    mv "$tmp_reg" "$MODEL_REGISTRY"
  }

  # Atomic registry update under flock
  (
    flock -x 201
    export _FB_SLUG="$model_slug"
    export _FB_STATUS="$new_status"
    export _FB_AVG_METRICS="${avg_metrics:-"{}"}"
    _update_registry
  ) 201>"${MODEL_REGISTRY}.lock"
  echo "  Registry updated: $MODEL_REGISTRY" >&2
else
  echo "  Warning: could not update registry (registry file missing)" >&2
fi

echo "" >&2
echo "Qualification run $qual_run_id complete." >&2
