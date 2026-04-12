#!/usr/bin/env bash
# fluxbench-qualify.sh — run qualification suite for a candidate model
# Usage: fluxbench-qualify.sh <model-slug> [--mock] [--emit] [--score] [--fixtures-dir <dir>] [--work-dir <dir>]
#
# Modes:
#   --mock                 Single-pass mock qualification (ground-truth as model output)
#   --emit                 Emit JSON descriptors for orchestrator (real mode), then exit
#   --score --work-dir D   Score completed responses from work directory (real mode)
#   (none of the above)    Error — must specify --mock, --emit, or --score
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/../config/flux-drive"
DEFAULT_FIXTURES_DIR="${SCRIPT_DIR}/../tests/fixtures/qualification"
MODEL_REGISTRY="${MODEL_REGISTRY:-${CONFIG_DIR}/model-registry.yaml}"

# --- Argument parsing ---
model_slug=""
mock_mode=false
emit_mode=false
score_mode=false
fixtures_dir="$DEFAULT_FIXTURES_DIR"
work_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mock)         mock_mode=true; shift ;;
    --emit)         emit_mode=true; shift ;;
    --score)        score_mode=true; shift ;;
    --fixtures-dir) fixtures_dir="$2"; shift 2 ;;
    --work-dir)     work_dir="$2"; shift 2 ;;
    -*)             echo "Error: unknown flag $1" >&2; exit 1 ;;
    *)
      if [[ -z "$model_slug" ]]; then
        model_slug="$1"; shift
      else
        echo "Error: unexpected argument $1" >&2; exit 1
      fi
      ;;
  esac
done

[[ -n "$model_slug" ]] || { echo "Usage: fluxbench-qualify.sh <model-slug> [--mock] [--emit] [--score] [--fixtures-dir <dir>] [--work-dir <dir>]" >&2; exit 1; }

# Validate model_slug format (matches discover-merge.sh VALID_SLUG pattern)
if [[ ! "$model_slug" =~ ^[a-zA-Z0-9][a-zA-Z0-9/_.-]{0,127}$ ]]; then
  echo "Error: invalid model slug format: $model_slug" >&2
  echo "  Slug must match: ^[a-zA-Z0-9][a-zA-Z0-9/_.-]{0,127}$" >&2
  exit 1
fi

# --- Validate mode flags (exactly one required) ---
mode_count=0
$mock_mode && mode_count=$((mode_count + 1))
$emit_mode && mode_count=$((mode_count + 1))
$score_mode && mode_count=$((mode_count + 1))
if [[ $mode_count -eq 0 ]]; then
  echo "Error: must specify one of --mock, --emit, or --score" >&2; exit 1
fi
if [[ $mode_count -gt 1 ]]; then
  echo "Error: --mock, --emit, and --score are mutually exclusive" >&2; exit 1
fi

# --- Validate fixtures directory (needed for --mock and --emit) ---
if $mock_mode || $emit_mode; then
  [[ -d "$fixtures_dir" ]] || { echo "Error: fixtures directory not found: $fixtures_dir" >&2; exit 1; }

  fixture_dirs=()
  for d in "$fixtures_dir"/fixture-*/; do
    [[ -d "$d" ]] && fixture_dirs+=("$d")
  done

  [[ ${#fixture_dirs[@]} -gt 0 ]] || { echo "Error: no fixture-* directories found in $fixtures_dir" >&2; exit 1; }
fi

# --- Validate --score prerequisites ---
if $score_mode; then
  [[ -n "$work_dir" ]] || { echo "Error: --score requires --work-dir <path>" >&2; exit 1; }
  [[ -d "$work_dir" ]] || { echo "Error: work directory not found: $work_dir" >&2; exit 1; }
  [[ -f "${work_dir}/manifest.json" ]] || { echo "Error: manifest.json not found in work directory: $work_dir" >&2; exit 1; }
fi

# ============================================================
# --emit mode: output JSON descriptors for orchestrator, exit
# ============================================================
if $emit_mode; then
  work_dir=$(mktemp -d /tmp/fluxbench-qual-XXXX)
  manifest_entries=()

  for fixture_dir in "${fixture_dirs[@]}"; do
    fixture_id=$(basename "$fixture_dir")
    ground_truth="${fixture_dir}/ground-truth.json"

    [[ -f "$ground_truth" ]] || { echo "Warning: no ground-truth.json in $fixture_dir — skipping" >&2; continue; }

    # Extract agent_type from ground-truth
    agent_type=$(jq -r '.agent_type // "unknown"' "$ground_truth")

    # Create response directory
    mkdir -p "${work_dir}/${fixture_id}"

    abs_fixture_dir="$(cd "$fixture_dir" && pwd)"
    response_path="${work_dir}/${fixture_id}/response.json"
    ground_truth_abs="${abs_fixture_dir}/ground-truth.json"
    document_path="${abs_fixture_dir}/document.md"

    # Output JSON descriptor to stdout (one per line)
    export _FB_EMIT_FIXTURE_ID="$fixture_id"
    export _FB_EMIT_SLUG="$model_slug"
    export _FB_EMIT_DOC_PATH="$document_path"
    export _FB_EMIT_AGENT_TYPE="$agent_type"
    export _FB_EMIT_RESP_PATH="$response_path"
    export _FB_EMIT_GT_PATH="$ground_truth_abs"
    python3 -c "
import json, os
desc = {
    'action': 'qualify',
    'fixture_id': os.environ['_FB_EMIT_FIXTURE_ID'],
    'model_slug': os.environ['_FB_EMIT_SLUG'],
    'document_path': os.environ['_FB_EMIT_DOC_PATH'],
    'agent_type': os.environ['_FB_EMIT_AGENT_TYPE'],
    'response_path': os.environ['_FB_EMIT_RESP_PATH'],
    'ground_truth_path': os.environ['_FB_EMIT_GT_PATH'],
}
print(json.dumps(desc))
"

    manifest_entries+=("$fixture_id")
  done

  # Write manifest
  export _FB_EMIT_WORK_DIR="$work_dir"
  export _FB_EMIT_MANIFEST_SLUG="$model_slug"
  export _FB_EMIT_MANIFEST_ENTRIES="$(printf '%s\n' "${manifest_entries[@]}")"
  python3 -c "
import json, os

work_dir = os.environ['_FB_EMIT_WORK_DIR']
slug = os.environ['_FB_EMIT_MANIFEST_SLUG']
entries_raw = os.environ['_FB_EMIT_MANIFEST_ENTRIES']
entries = [e for e in entries_raw.strip().split('\n') if e]

manifest = {
    'model_slug': slug,
    'work_dir': work_dir,
    'fixtures': entries,
}
with open(os.path.join(work_dir, 'manifest.json'), 'w') as f:
    json.dump(manifest, f, indent=2)
"

  echo "work_dir=${work_dir}" >&2
  echo "Next: dispatch model responses, then run:" >&2
  echo "  fluxbench-qualify.sh ${model_slug} --score --work-dir ${work_dir}" >&2
  exit 0
fi

# ============================================================
# --score mode: read completed responses, score, aggregate
# ============================================================
if $score_mode; then
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  epoch=$(date +%s)
  qual_run_id="qr-${model_slug}-${epoch}"

  echo "Starting score phase: $qual_run_id" >&2
  echo "  Model: $model_slug" >&2
  echo "  Work dir: $work_dir" >&2

  # Read manifest
  export _FB_SCORE_MANIFEST="${work_dir}/manifest.json"
  fixture_list=$(python3 -c "
import json, os
with open(os.environ['_FB_SCORE_MANIFEST']) as f:
    m = json.load(f)
for fid in m['fixtures']:
    print(fid)
")

  total_fixtures=0
  valid_outputs=0
  all_results=()
  overall_pass=true
  failure_reasons=()

  # Create a temp dir for scoring artifacts (cleaned up on exit)
  score_tmp=$(mktemp -d)
  trap 'rm -rf "$score_tmp"' EXIT

  while IFS= read -r fixture_id; do
    [[ -n "$fixture_id" ]] || continue
    total_fixtures=$((total_fixtures + 1))

    response_file="${work_dir}/${fixture_id}/response.json"
    # Locate ground-truth: use --fixtures-dir if provided, else default
    ground_truth="${fixtures_dir}/${fixture_id}/ground-truth.json"

    echo "  Scoring fixture: $fixture_id" >&2

    # Check ground-truth exists first (before counting valid_outputs)
    if [[ ! -f "$ground_truth" ]]; then
      echo "  FAIL: $fixture_id — ground-truth not found: $ground_truth" >&2
      overall_pass=false
      failure_reasons+=("$fixture_id: ground-truth missing")
      continue
    fi

    # Check response file exists
    if [[ ! -f "$response_file" ]]; then
      echo "  FAIL: $fixture_id — response file missing: $response_file" >&2
      overall_pass=false
      failure_reasons+=("$fixture_id: response file missing")
      continue
    fi

    # Validate response is valid JSON with findings array
    if ! jq -e '.findings' "$response_file" >/dev/null 2>&1; then
      echo "  FAIL: $fixture_id — response missing findings array" >&2
      overall_pass=false
      failure_reasons+=("$fixture_id: response missing findings array")
      continue
    fi

    valid_outputs=$((valid_outputs + 1))

    agent_type=$(jq -r '.agent_type // "unknown"' "$ground_truth")

    qual_output="${score_tmp}/${fixture_id}-qual-output.json"
    result_output="${score_tmp}/${fixture_id}-result.json"

    # Build qualification output JSON from response
    jq -n \
      --arg model_slug "$model_slug" \
      --arg qual_run_id "$qual_run_id" \
      --arg agent_type "$agent_type" \
      --arg timestamp "$timestamp" \
      --argjson findings "$(jq -c '.findings // []' "$response_file")" \
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

    # Invoke fluxbench-score.sh
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
  done <<< "$fixture_list"

  echo "  Mode: real" >&2

  # --- Compute final format_compliance_rate ---
  export _FB_VALID="$valid_outputs"
  export _FB_TOTAL="$total_fixtures"
  if [[ $total_fixtures -gt 0 ]]; then
    format_compliance_rate=$(python3 -c "
import os
print(round(int(os.environ['_FB_VALID']) / int(os.environ['_FB_TOTAL']), 4))
")
  else
    format_compliance_rate="0.0"
  fi

  echo "" >&2
  echo "Qualification summary:" >&2
  echo "  Format compliance rate: $format_compliance_rate" >&2
  echo "  Fixtures passed: $((total_fixtures - ${#failure_reasons[@]}))/$total_fixtures" >&2

  # --- Aggregate scores across all fixtures ---
  avg_metrics="{}"
  if [[ ${#all_results[@]} -gt 0 ]]; then
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
  export _FB_QUAL_MODE="real"

  if [[ -f "$MODEL_REGISTRY" ]]; then
    _update_registry() {
      local tmp_reg
      tmp_reg=$(mktemp)
      trap 'rm -f "$tmp_reg"' RETURN
      export _FB_TMP_REG="$tmp_reg"

      cp "$MODEL_REGISTRY" "$tmp_reg"

      python3 -c "
import yaml, json, sys, os

reg_path = os.environ['_FB_TMP_REG']
slug = os.environ['_FB_SLUG']
new_status = os.environ['_FB_STATUS']
avg_json = os.environ.get('_FB_AVG_METRICS') or '{}'
qual_mode = os.environ.get('_FB_QUAL_MODE')
if not qual_mode or qual_mode not in ('real', 'mock'):
    raise ValueError(f'_FB_QUAL_MODE must be real or mock, got: {qual_mode!r}')

with open(reg_path) as f:
    reg = yaml.safe_load(f)

if reg is None:
    reg = {}
if 'models' not in reg or reg['models'] is None:
    reg['models'] = {}
if isinstance(reg['models'], list):
    reg['models'] = {}

model = reg['models'].get(slug)
if model is None:
    model = {}
    reg['models'][slug] = model

model['status'] = new_status
model['qualified_via'] = qual_mode

metrics = json.loads(avg_json) if avg_json else {}
if metrics:
    if 'fluxbench' not in model or model['fluxbench'] is None:
        model['fluxbench'] = {}
    fb = model['fluxbench']
    fb['format_compliance'] = metrics.get('fluxbench-format-compliance')
    fb['finding_recall'] = metrics.get('fluxbench-finding-recall')
    fb['false_positive_rate'] = metrics.get('fluxbench-false-positive-rate')
    fb['severity_accuracy'] = metrics.get('fluxbench-severity-accuracy')

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

      export _FB_TMP_REG_VAL="$tmp_reg"
      python3 -c "import yaml, os; yaml.safe_load(open(os.environ['_FB_TMP_REG_VAL']))" || { echo "Error: registry validation failed" >&2; return 1; }
      mv "$tmp_reg" "$MODEL_REGISTRY"
    }

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
  exit 0
fi

# ============================================================
# --mock mode: single-pass qualification (existing behavior)
# ============================================================

# --- Qualification run metadata ---
timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
epoch=$(date +%s)
qual_run_id="qr-${model_slug}-${epoch}"

echo "Starting qualification run: $qual_run_id" >&2
echo "  Model: $model_slug" >&2
echo "  Fixtures: ${#fixture_dirs[@]}" >&2
echo "  Mode: mock" >&2

# --- Temp workspace ---
mock_work_dir=$(mktemp -d)
trap 'rm -rf "$mock_work_dir"' EXIT

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
  model_output="$ground_truth"
  valid_outputs=$((valid_outputs + 1))

  # Build qualification-output.json per fixture
  qual_output="${mock_work_dir}/${fixture_id}-qual-output.json"
  result_output="${mock_work_dir}/${fixture_id}-result.json"

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
export _FB_VALID="$valid_outputs"
export _FB_TOTAL="$total_fixtures"
if [[ $total_fixtures -gt 0 ]]; then
  format_compliance_rate=$(python3 -c "
import os
print(round(int(os.environ['_FB_VALID']) / int(os.environ['_FB_TOTAL']), 4))
")
else
  format_compliance_rate="0.0"
fi

echo "" >&2
echo "Qualification summary:" >&2
echo "  Format compliance rate: $format_compliance_rate" >&2
echo "  Fixtures passed: $((total_fixtures - ${#failure_reasons[@]}))/$total_fixtures" >&2

# --- Aggregate scores across all fixtures ---
avg_metrics="{}"
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
export _FB_QUAL_MODE="mock"

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
qual_mode = os.environ.get('_FB_QUAL_MODE')
if not qual_mode or qual_mode not in ('real', 'mock'):
    raise ValueError(f'_FB_QUAL_MODE must be real or mock, got: {qual_mode!r}')

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
model['qualified_via'] = qual_mode

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
    export _FB_TMP_REG_VAL="$tmp_reg"
    python3 -c "import yaml, os; yaml.safe_load(open(os.environ['_FB_TMP_REG_VAL']))" || { echo "Error: registry validation failed" >&2; return 1; }
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
