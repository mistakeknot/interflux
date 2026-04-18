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

# Compute metrics via Python — finding matching with bipartite constraint
export _FB_MODEL_FINDINGS="$model_findings"
export _FB_BASELINE_FINDINGS="$baseline_findings"
export _FB_FORMAT_COMPLIANCE="$format_compliance"
export _FB_T_FORMAT="$t_format"
export _FB_T_RECALL="$t_recall"
export _FB_T_FP="$t_fp"
export _FB_T_SEVERITY="$t_severity"
result_json=$(python3 -c "
import json, sys, os
from difflib import SequenceMatcher

model_findings = json.loads(os.environ['_FB_MODEL_FINDINGS'])
baseline_findings = json.loads(os.environ['_FB_BASELINE_FINDINGS'])

# Normalize severity values: LLM output often has trailing whitespace / lowercase variants.
# Without this, 'P0 ' (trailing space) fails equality against 'P0' and auto-fail rules skip.
def _sev(finding):
    return (finding.get('severity') or '').strip().upper()

# Severity weights
WEIGHTS = {'P0': 4, 'P1': 2, 'P2': 1, 'P3': 0.5}
# Severity levels for ±1 accuracy check
SEV_LEVELS = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}

def normalize_location(loc):
    loc = loc.lstrip('./')
    return loc.lower()

def parse_loc_parts(loc):
    \"\"\"Split 'file.py:10-12' into (file, start_line) or (file, None).\"\"\"
    parts = loc.split(':')
    if len(parts) < 2:
        return (loc, None)
    try:
        line = int(parts[1].split('-')[0])
        return (parts[0], line)
    except ValueError:
        return (parts[0], None)

def location_score(m_loc, b_loc):
    \"\"\"Fuzzy location matching: exact=1.0, same file ±5 lines=0.5-0.9, else 0.\"\"\"
    m_norm = normalize_location(m_loc)
    b_norm = normalize_location(b_loc)
    if m_norm == b_norm:
        return 1.0
    m_file, m_line = parse_loc_parts(m_norm)
    b_file, b_line = parse_loc_parts(b_norm)
    if m_file != b_file:
        return 0.0
    if m_line is not None and b_line is not None:
        delta = abs(m_line - b_line)
        if delta <= 5:
            return max(0.5, 1.0 - delta * 0.1)
    return 0.0

def match_score(m, b):
    desc_ratio = SequenceMatcher(None,
        m.get('description', '').lower(),
        b.get('description', '').lower()
    ).ratio()
    loc_s = location_score(m.get('location', ''), b.get('location', ''))
    if loc_s > 0:
        return loc_s * desc_ratio
    # Location mismatch but high description similarity — credit with penalty
    if desc_ratio >= 0.60:
        return 0.4 * desc_ratio
    return 0.0

# Optimal bipartite matching via Hungarian algorithm (pure Python)
def hungarian_maximize(score_matrix):
    \"\"\"Optimal assignment for small matrices. Returns list of (row, col) pairs.\"\"\"
    n = len(score_matrix)
    if n == 0:
        return []
    m = len(score_matrix[0]) if n > 0 else 0
    if m == 0:
        return []

    # Pad to square matrix with zeros
    size = max(n, m)
    max_val = max(max(row) for row in score_matrix) if score_matrix else 0
    cost = [[0.0] * size for _ in range(size)]
    # Convert to minimization (negate scores)
    for i in range(n):
        for j in range(m):
            cost[i][j] = max_val - score_matrix[i][j]

    # Hungarian algorithm
    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)

    for i in range(1, size + 1):
        p[0] = i
        j0 = 0
        minv = [float('inf')] * (size + 1)
        used = [False] * (size + 1)

        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float('inf')
            j1 = -1

            for j in range(1, size + 1):
                if not used[j]:
                    cur = cost[i0-1][j-1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j

            for j in range(size + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta

            j0 = j1
            if p[j0] == 0:
                break

        while j0:
            p[j0] = p[way[j0]]
            j0 = way[j0]

    result = []
    for j in range(1, size + 1):
        if p[j] != 0 and p[j] <= n and j <= m:
            if score_matrix[p[j]-1][j-1] >= 0.20:  # minimum threshold
                result.append((p[j]-1, j-1))
    return result

# Build score matrix
n_model = len(model_findings)
n_baseline = len(baseline_findings)
if n_model > 0 and n_baseline > 0:
    score_matrix = []
    for mi in range(n_model):
        row = []
        for bi in range(n_baseline):
            s = match_score(model_findings[mi], baseline_findings[bi])
            row.append(s)
        score_matrix.append(row)
    matched_pairs = hungarian_maximize(score_matrix)
    used_model = set(mi for mi, bi in matched_pairs)
    used_baseline = set(bi for mi, bi in matched_pairs)
else:
    matched_pairs = []
    used_model = set()
    used_baseline = set()

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
    # Note: if total_weight == 0 and len(model_findings) > 0, all model findings
    # are false positives — fp_rate will be 1.0 via model_only_idxs computation below.
elif found_weight == 0 and total_weight > 0:
    recall = 0.0
else:
    recall = round(found_weight / total_weight, 4)

# P0 auto-fail — use _sev() to tolerate trailing whitespace / case drift in LLM output
p0_auto_fail = False
for bi in range(len(baseline_findings)):
    if _sev(baseline_findings[bi]) == 'P0' and bi in [b for _, b in matched_pairs]:
        continue
    elif _sev(baseline_findings[bi]) == 'P0':
        p0_auto_fail = True
        break

# P0 severity downgrade check: matched P0 findings must be reported as P0
if not p0_auto_fail:
    for mi, bi in matched_pairs:
        if _sev(baseline_findings[bi]) == 'P0':
            if _sev(model_findings[mi]) != 'P0':
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

# Gate evaluation — env-var-safe, no shell interpolation
format_compliance = float(os.environ['_FB_FORMAT_COMPLIANCE'])
t_format = float(os.environ.get('_FB_T_FORMAT', '0.95'))
t_recall = float(os.environ.get('_FB_T_RECALL', '0.60'))
t_fp = float(os.environ.get('_FB_T_FP', '0.20'))
t_severity = float(os.environ.get('_FB_T_SEVERITY', '0.70'))

gate_format = format_compliance >= t_format
gate_recall = recall >= t_recall and not p0_auto_fail
gate_fp = fp_rate <= t_fp
gate_severity = severity_accuracy >= t_severity

result = {
    'recall': clean_num(recall),
    'fp_rate': clean_num(fp_rate),
    'severity_accuracy': clean_num(severity_accuracy),
    'p0_auto_fail': p0_auto_fail,
    'disagreement_rate': clean_num(disagreement_rate),
    'matched': len(matched_pairs),
    'model_only': len(model_only_idxs),
    'baseline_only': len(baseline_only_idxs),
    'gate_format': gate_format,
    'gate_recall': gate_recall,
    'gate_fp': gate_fp,
    'gate_severity': gate_severity
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
