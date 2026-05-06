#!/usr/bin/env bash
# fluxbench-score.sh — score qualification output against a baseline
# Usage: fluxbench-score.sh <qualification-output.json> <baseline.json> <output-result.json>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/../config/flux-drive"

qual_output="${1:?Usage: fluxbench-score.sh <qualification-output.json> <baseline.json> <output-result.json>}"
baseline="${2:?Missing baseline.json}"
result_output="${3:?Missing output-result.json}"

results_jsonl="${FLUXBENCH_RESULTS_JSONL:-${SCRIPT_DIR}/../data/fluxbench-results.jsonl}"
mkdir -p "$(dirname "$results_jsonl")"

# Validate inputs exist
[[ -f "$qual_output" ]] || { echo "Error: qualification output not found: $qual_output" >&2; exit 1; }
[[ -f "$baseline" ]]    || { echo "Error: baseline not found: $baseline" >&2; exit 1; }

# Extract qualification_run_id — fail if missing
qual_run_id=$(jq -r '.metadata.qualification_run_id // empty' "$qual_output")
[[ -n "$qual_run_id" ]] || { echo "Error: metadata.qualification_run_id missing from qualification output" >&2; exit 1; }

# Extract model_slug
model_slug=$(jq -r '.model_slug // "unknown"' "$qual_output")

# Extract format_compliance_rate from qualification output
format_compliance=$(jq -r '.format_compliance_rate // 1.0' "$qual_output")

# Load thresholds (prefer calibrated thresholds, fall back to metrics defaults)
thresholds_file="${CONFIG_DIR}/fluxbench-thresholds.yaml"
metrics_file="${CONFIG_DIR}/fluxbench-metrics.yaml"

_get_threshold() {
  local metric="$1" default="$2"
  local val=""
  local yq_err
  # If the thresholds file exists but yq fails on it, that's a calibration problem — surface
  # it (not hide behind the hardcoded default). The hardcoded default is the correct fallback
  # only when the file is absent.
  if [[ -f "$thresholds_file" ]] && command -v yq >/dev/null 2>&1; then
    yq_err=$(mktemp)
    if val=$(yq ".thresholds.\"${metric}\"" "$thresholds_file" 2>"$yq_err"); then
      :
    else
      echo "fluxbench-score: failed to read threshold '$metric' from $thresholds_file (using default $default)" >&2
      cat "$yq_err" >&2
      val=""
    fi
    rm -f "$yq_err"
  fi
  if [[ -z "$val" || "$val" == "null" ]] && [[ -f "$metrics_file" ]] && command -v yq >/dev/null 2>&1; then
    yq_err=$(mktemp)
    if val=$(yq ".core_gates.\"${metric}\".threshold_default // .extended.\"${metric}\".threshold_default" "$metrics_file" 2>"$yq_err"); then
      :
    else
      echo "fluxbench-score: failed to read default threshold '$metric' from $metrics_file" >&2
      cat "$yq_err" >&2
      val=""
    fi
    rm -f "$yq_err"
  fi
  echo "${val:-$default}"
}

t_format=$(_get_threshold "fluxbench-format-compliance" "0.95")
t_recall=$(_get_threshold "fluxbench-finding-recall" "0.60")
t_fp=$(_get_threshold "fluxbench-false-positive-rate" "0.20")
t_severity=$(_get_threshold "fluxbench-severity-accuracy" "0.70")
t_persona=$(_get_threshold "fluxbench-persona-adherence" "0.60")

# Extract findings arrays
model_findings=$(jq -c '.findings // []' "$qual_output")
baseline_findings=$(jq -c '.findings // []' "$baseline")

# Compute metrics via the extracted scoring algorithm (scripts/_fluxbench_score.py).
# The 180-line Hungarian / severity / gate logic now lives in a testable Python
# module — see scripts/tests/test_fluxbench_score.py. This shell wrapper just
# materializes the JSON inputs and invokes the script.
_fb_model_tmp=$(mktemp --suffix=-model-findings.json)
_fb_baseline_tmp=$(mktemp --suffix=-baseline-findings.json)
trap 'rm -f "$_fb_model_tmp" "$_fb_baseline_tmp"' EXIT
printf '%s' "$model_findings" > "$_fb_model_tmp"
printf '%s' "$baseline_findings" > "$_fb_baseline_tmp"

result_json=$(python3 "${SCRIPT_DIR:-$(dirname "${BASH_SOURCE[0]}")}/_fluxbench_score.py" \
  "$_fb_model_tmp" "$_fb_baseline_tmp" "$format_compliance" \
  --t-format "$t_format" \
  --t-recall "$t_recall" \
  --t-fp "$t_fp" \
  --t-severity "$t_severity")

# Parse Python output
recall=$(echo "$result_json" | jq -r '.recall')
fp_rate=$(echo "$result_json" | jq -r '.fp_rate')
severity_accuracy=$(echo "$result_json" | jq -r '.severity_accuracy')
p0_auto_fail=$(echo "$result_json" | jq -r '.p0_auto_fail')
disagreement_rate=$(echo "$result_json" | jq -r '.disagreement_rate')
matched=$(echo "$result_json" | jq -r '.matched')
model_only=$(echo "$result_json" | jq -r '.model_only')
baseline_only=$(echo "$result_json" | jq -r '.baseline_only')

timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Read gate results from Python evaluation (no shell float comparison needed)
gate_format=$(echo "$result_json" | jq -r '.gate_format')
gate_recall=$(echo "$result_json" | jq -r '.gate_recall')
gate_fp=$(echo "$result_json" | jq -r '.gate_fp')
gate_severity=$(echo "$result_json" | jq -r '.gate_severity')

# Overall pass: all computable gates must pass AND no P0 auto-fail
overall_pass="true"
for g in "$gate_format" "$gate_recall" "$gate_fp" "$gate_severity"; do
  [[ "$g" == "true" ]] || overall_pass="false"
done
[[ "$p0_auto_fail" == "false" ]] || overall_pass="false"

# Build result JSON
output=$(jq -n \
  --arg model_slug "$model_slug" \
  --arg qual_run_id "$qual_run_id" \
  --arg timestamp "$timestamp" \
  --argjson format_compliance "$format_compliance" \
  --argjson recall "$recall" \
  --argjson fp_rate "$fp_rate" \
  --argjson severity_accuracy "$severity_accuracy" \
  --argjson disagreement_rate "$disagreement_rate" \
  --argjson t_format "$t_format" \
  --argjson t_recall "$t_recall" \
  --argjson t_fp "$t_fp" \
  --argjson t_severity "$t_severity" \
  --argjson t_persona "$t_persona" \
  --argjson gate_format "$(echo "$gate_format")" \
  --argjson gate_recall "$(echo "$gate_recall")" \
  --argjson gate_fp "$(echo "$gate_fp")" \
  --argjson gate_severity "$(echo "$gate_severity")" \
  --argjson p0_auto_fail "$p0_auto_fail" \
  --argjson overall_pass "$overall_pass" \
  --argjson matched "$matched" \
  --argjson model_only "$model_only" \
  --argjson baseline_only "$baseline_only" \
  '{
    model_slug: $model_slug,
    qualification_run_id: $qual_run_id,
    timestamp: $timestamp,
    metrics: {
      "fluxbench-format-compliance": $format_compliance,
      "fluxbench-finding-recall": $recall,
      "fluxbench-false-positive-rate": $fp_rate,
      "fluxbench-severity-accuracy": $severity_accuracy,
      "fluxbench-persona-adherence": null,
      "fluxbench-instruction-compliance": null,
      "fluxbench-disagreement-rate": $disagreement_rate,
      "fluxbench-latency-p50": null,
      "fluxbench-token-efficiency": null
    },
    gate_results: {
      "fluxbench-format-compliance": {value: $format_compliance, threshold: $t_format, passed: $gate_format},
      "fluxbench-finding-recall": {value: $recall, threshold: $t_recall, passed: $gate_recall, p0_auto_fail: $p0_auto_fail},
      "fluxbench-false-positive-rate": {value: $fp_rate, threshold: $t_fp, passed: $gate_fp},
      "fluxbench-severity-accuracy": {value: $severity_accuracy, threshold: $t_severity, passed: $gate_severity},
      "fluxbench-persona-adherence": {value: null, threshold: $t_persona, passed: null}
    },
    overall_pass: $overall_pass,
    finding_match_detail: {matched: $matched, model_only: $model_only, baseline_only: $baseline_only}
  }')

# Write result JSON
echo "$output" > "$result_output"

# Append to JSONL under flock
json_line=$(echo "$output" | jq -c .)
(flock -x 200; echo "$json_line" >> "$results_jsonl") 200>"${results_jsonl}.lock"

echo "Score complete: overall_pass=$overall_pass recall=$recall fp_rate=$fp_rate severity_accuracy=$severity_accuracy" >&2
