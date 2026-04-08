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
  if [[ -f "$thresholds_file" ]] && command -v yq >/dev/null 2>&1; then
    val=$(yq -r ".thresholds.\"${metric}\" // empty" "$thresholds_file" 2>/dev/null || true)
  fi
  if [[ -z "$val" || "$val" == "null" ]] && [[ -f "$metrics_file" ]] && command -v yq >/dev/null 2>&1; then
    val=$(yq -r ".core_gates.\"${metric}\".threshold_default // .extended.\"${metric}\".threshold_default // empty" "$metrics_file" 2>/dev/null || true)
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

# Compute metrics via Python — finding matching with bipartite constraint
export _FB_MODEL_FINDINGS="$model_findings"
export _FB_BASELINE_FINDINGS="$baseline_findings"
result_json=$(python3 -c "
import json, sys, os
from difflib import SequenceMatcher

model_findings = json.loads(os.environ['_FB_MODEL_FINDINGS'])
baseline_findings = json.loads(os.environ['_FB_BASELINE_FINDINGS'])

# Severity weights
WEIGHTS = {'P0': 4, 'P1': 2, 'P2': 1, 'P3': 0.5}
# Severity levels for ±1 accuracy check
SEV_LEVELS = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}

def normalize_location(loc):
    loc = loc.lstrip('./')
    return loc.lower()

def match_score(m, b):
    loc_match = normalize_location(m.get('location', '')) == normalize_location(b.get('location', ''))
    if not loc_match:
        return 0.0
    desc_ratio = SequenceMatcher(None,
        m.get('description', '').lower(),
        b.get('description', '').lower()
    ).ratio()
    return desc_ratio

# Greedy bipartite matching: best match first, no credit-stacking
matches = []  # (model_idx, baseline_idx, score)
for mi, mf in enumerate(model_findings):
    for bi, bf in enumerate(baseline_findings):
        s = match_score(mf, bf)
        if s >= 0.70:
            matches.append((mi, bi, s))

# Sort by score descending, greedily assign
matches.sort(key=lambda x: -x[2])
used_model = set()
used_baseline = set()
matched_pairs = []  # (model_idx, baseline_idx)

for mi, bi, s in matches:
    if mi not in used_model and bi not in used_baseline:
        used_model.add(mi)
        used_baseline.add(bi)
        matched_pairs.append((mi, bi))

# Model-only and baseline-only
model_only_idxs = [i for i in range(len(model_findings)) if i not in used_model]
baseline_only_idxs = [i for i in range(len(baseline_findings)) if i not in used_baseline]

# Severity-weighted recall
total_weight = sum(WEIGHTS.get(bf.get('severity', 'P2'), 1) for bf in baseline_findings)
found_weight = sum(WEIGHTS.get(baseline_findings[bi].get('severity', 'P2'), 1) for _, bi in matched_pairs)

def clean_num(v):
    \"\"\"Convert whole-number floats to int for JSON (1.0 -> 1).\"\"\"
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v

if total_weight == 0:
    recall = 1.0  # empty baseline
elif found_weight == 0 and total_weight > 0:
    recall = 0.0
else:
    recall = round(found_weight / total_weight, 4)

# P0 auto-fail
p0_auto_fail = False
for bi in range(len(baseline_findings)):
    if baseline_findings[bi].get('severity') == 'P0' and bi in [b for _, b in matched_pairs]:
        continue
    elif baseline_findings[bi].get('severity') == 'P0':
        p0_auto_fail = True
        break

# False positive rate
if len(model_findings) == 0:
    fp_rate = 0.0
else:
    fp_rate = round(len(model_only_idxs) / len(model_findings), 4)

# Severity accuracy: % of matched where severity is ±1 level
sev_accurate = 0
for mi, bi in matched_pairs:
    m_sev = SEV_LEVELS.get(model_findings[mi].get('severity', 'P2'), 2)
    b_sev = SEV_LEVELS.get(baseline_findings[bi].get('severity', 'P2'), 2)
    if abs(m_sev - b_sev) <= 1:
        sev_accurate += 1

if len(matched_pairs) == 0:
    severity_accuracy = 1.0 if len(baseline_findings) == 0 else 0.0
else:
    severity_accuracy = round(sev_accurate / len(matched_pairs), 4)

# Disagreement rate (same as FP rate for now — findings unique to model)
if len(model_findings) == 0:
    disagreement_rate = 0.0
else:
    disagreement_rate = round(len(model_only_idxs) / len(model_findings), 4)

result = {
    'recall': clean_num(recall),
    'fp_rate': clean_num(fp_rate),
    'severity_accuracy': clean_num(severity_accuracy),
    'p0_auto_fail': p0_auto_fail,
    'disagreement_rate': clean_num(disagreement_rate),
    'matched': len(matched_pairs),
    'model_only': len(model_only_idxs),
    'baseline_only': len(baseline_only_idxs)
}
print(json.dumps(result))
")

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

# Evaluate gates
_gate_pass() {
  local value="$1" threshold="$2" higher_is_better="${3:-true}"
  if [[ "$higher_is_better" == "true" ]]; then
    python3 -c "print('true' if float('$value') >= float('$threshold') else 'false')"
  else
    python3 -c "print('true' if float('$value') <= float('$threshold') else 'false')"
  fi
}

gate_format=$(_gate_pass "$format_compliance" "$t_format" "true")
gate_recall=$(_gate_pass "$recall" "$t_recall" "true")
gate_fp=$(_gate_pass "$fp_rate" "$t_fp" "false")
gate_severity=$(_gate_pass "$severity_accuracy" "$t_severity" "true")

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
