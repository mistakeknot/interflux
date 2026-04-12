#!/usr/bin/env bash
# fluxbench-challenger.sh — challenger slot lifecycle management
# Usage: fluxbench-challenger.sh <action> [args]
#   select                  — select best challenger candidate from registry
#   evaluate <model-slug>   — evaluate a challenger after N runs
#   status                  — show current challenger slot status
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/../config/flux-drive"

export MODEL_REGISTRY="${MODEL_REGISTRY:-${CONFIG_DIR}/model-registry.yaml}"
export BUDGET_CONFIG="${BUDGET_CONFIG:-${CONFIG_DIR}/budget.yaml}"
export RESULTS_JSONL="${FLUXBENCH_RESULTS_JSONL:-${SCRIPT_DIR}/../data/fluxbench-results.jsonl}"

action="${1:-}"
shift || true

[[ -n "$action" ]] || {
  echo "Usage: fluxbench-challenger.sh <select|evaluate|status>" >&2
  exit 1
}

# --- Helpers ---

_require_file() {
  local path="$1" label="$2"
  [[ -f "$path" ]] || { echo "Error: ${label} not found: ${path}" >&2; exit 1; }
}

_count_runs() {
  local slug="$1"
  if [[ ! -f "$RESULTS_JSONL" ]]; then
    echo 0
    return
  fi
  jq -c --arg slug "$slug" 'select(.model_slug == $slug)' "$RESULTS_JSONL" 2>/dev/null | wc -l | tr -d ' '
}

# Atomic registry write: set a model's status field
# Args: $1 = model slug, $2 = new status
_set_model_status() {
  local slug="$1" new_status="$2"
  (
    flock -x 201
    _tmp_reg=$(mktemp)
    trap 'rm -f "$_tmp_reg"' EXIT
    cp "$MODEL_REGISTRY" "$_tmp_reg"

    export _FB_TMP_REG="$_tmp_reg"
    export _FB_SLUG="$slug"
    export _FB_NEW_STATUS="$new_status"
    python3 -c "
import yaml, json, sys, os

reg_path = os.environ['_FB_TMP_REG']
slug = os.environ['_FB_SLUG']
new_status = os.environ['_FB_NEW_STATUS']

with open(reg_path) as f:
    reg = yaml.safe_load(f) or {}

if 'models' not in reg or reg['models'] is None:
    reg['models'] = {}

model = reg['models'].get(slug) if isinstance(reg['models'], dict) else None
if model is None and isinstance(reg['models'], list):
    for m in reg['models']:
        if isinstance(m, dict) and m.get('model_id', '') == slug:
            model = m
            break

if model is not None:
    model['status'] = new_status

with open(reg_path, 'w') as f:
    yaml.dump(reg, f, default_flow_style=False, sort_keys=False)
"
    # Validate before swap
    python3 -c "import yaml, os; yaml.safe_load(open(os.environ['_FB_TMP_REG']))"
    mv "$_tmp_reg" "$MODEL_REGISTRY"
  ) 201>"${MODEL_REGISTRY}.lock"
}

# Atomic registry write: promote a model (set qualified + preserve qualified_via)
# Args: $1 = model slug
_promote_model() {
  local slug="$1"
  (
    flock -x 201
    _tmp_reg=$(mktemp)
    trap 'rm -f "$_tmp_reg"' EXIT
    cp "$MODEL_REGISTRY" "$_tmp_reg"

    export _FB_TMP_REG="$_tmp_reg"
    export _FB_SLUG="$slug"
    python3 -c "
import yaml, json, sys, os

reg_path = os.environ['_FB_TMP_REG']
slug = os.environ['_FB_SLUG']

with open(reg_path) as f:
    reg = yaml.safe_load(f) or {}

if 'models' not in reg or reg['models'] is None:
    reg['models'] = {}

model = reg['models'].get(slug) if isinstance(reg['models'], dict) else None
if model is None and isinstance(reg['models'], list):
    for m in reg['models']:
        if isinstance(m, dict) and m.get('model_id', '') == slug:
            model = m
            break

if model is not None:
    model['status'] = 'qualified'
    # Preserve qualified_via on promotion
    model['qualified_via'] = model.get('qualified_via') or 'unknown'
    if model['qualified_via'] == 'unknown':
        print(f'  WARNING: {slug} promoted without qualified_via — was it qualified?', file=sys.stderr)

with open(reg_path, 'w') as f:
    yaml.dump(reg, f, default_flow_style=False, sort_keys=False)
"
    # Validate before swap
    python3 -c "import yaml, os; yaml.safe_load(open(os.environ['_FB_TMP_REG']))"
    mv "$_tmp_reg" "$MODEL_REGISTRY"
  ) 201>"${MODEL_REGISTRY}.lock"
}

# --- Action: select ---
_action_select() {
  _require_file "$MODEL_REGISTRY" "model registry"
  _require_file "$BUDGET_CONFIG" "budget config"

  result=$(python3 -c "
import yaml, json, sys, os

reg_path = os.environ.get('MODEL_REGISTRY', '')
budget_path = os.environ.get('BUDGET_CONFIG', '')

with open(reg_path) as f:
    reg = yaml.safe_load(f) or {}

with open(budget_path) as f:
    budget = yaml.safe_load(f) or {}

challenger_cfg = budget.get('challenger', {})
pre_inclusion_runs = int(challenger_cfg.get('pre_inclusion_runs', 2))

models = reg.get('models', {}) or {}

# Handle both dict and list formats
if isinstance(models, list):
    model_items = [(m.get('model_id', ''), m) for m in models if isinstance(m, dict)]
else:
    model_items = [(k, v) for k, v in models.items() if isinstance(v, dict)]

# Filter: status in (qualifying, auto-qualified) AND has fluxbench scores
candidates = []
for slug, model in model_items:
    status = model.get('status', '')
    if status not in ('qualifying', 'auto-qualified'):
        continue
    # Only consider models qualified via real inference
    qual_via = model.get('qualified_via')
    if qual_via != 'real':
        continue
    fb = model.get('fluxbench')
    if not fb or not isinstance(fb, dict):
        continue
    # Compute aggregate score: average of non-null core gate values
    core_keys = ['format_compliance', 'finding_recall', 'false_positive_rate',
                 'severity_accuracy', 'persona_adherence']
    scores = []
    for k in core_keys:
        v = fb.get(k)
        if v is not None:
            # false_positive_rate: lower is better, invert for ranking
            if k == 'false_positive_rate':
                scores.append(1.0 - float(v))
            else:
                scores.append(float(v))
    if not scores:
        continue
    avg = sum(scores) / len(scores)
    candidates.append({'slug': slug, 'avg_score': round(avg, 4), 'status': status, 'model': model})

if not candidates:
    print(json.dumps({'selected': None, 'reason': 'no qualifying candidates'}))
    sys.exit(0)

# Rank by aggregate score descending
candidates.sort(key=lambda c: -c['avg_score'])
best = candidates[0]

print(json.dumps({
    'selected': best['slug'],
    'avg_score': best['avg_score'],
    'status': best['status'],
    'pre_inclusion_runs': pre_inclusion_runs,
    'candidates_evaluated': len(candidates),
    'provider': best['model'].get('provider', 'unknown'),
    'prompt_content_policy': best['model'].get('prompt_content_policy', 'fixtures_only'),
    'eligible_tiers': best['model'].get('eligible_tiers', []),
}))
" 2>&1)

  selected=$(echo "$result" | jq -r '.selected // empty')

  if [[ -z "$selected" || "$selected" == "null" ]]; then
    echo "$result"
    return 0
  fi

  # Pre-inclusion filter: check fixture run count
  pre_inclusion_runs=$(echo "$result" | jq -r '.pre_inclusion_runs')
  run_count=$(_count_runs "$selected")

  if [[ "$run_count" -lt "$pre_inclusion_runs" ]]; then
    jq -n \
      --arg slug "$selected" \
      --argjson runs "$run_count" \
      --argjson required "$pre_inclusion_runs" \
      '{"selected": null, "reason": "insufficient pre-inclusion runs", "model": $slug, "runs": $runs, "required": $required}'
    return 0
  fi

  # Mark as challenger in registry
  _set_model_status "$selected" "challenger" || { echo "Error: failed to update registry" >&2; return 1; }

  echo "Challenger selected: $selected" >&2

  avg_score=$(echo "$result" | jq -r '.avg_score')
  candidates_evaluated=$(echo "$result" | jq -r '.candidates_evaluated')
  provider=$(echo "$result" | jq -r '.provider')
  prompt_content_policy=$(echo "$result" | jq -r '.prompt_content_policy')
  eligible_tiers=$(echo "$result" | jq -c '.eligible_tiers')
  jq -n \
    --arg slug "$selected" \
    --argjson avg_score "$avg_score" \
    --argjson runs "$run_count" \
    --argjson candidates_evaluated "$candidates_evaluated" \
    --arg provider "$provider" \
    --arg prompt_content_policy "$prompt_content_policy" \
    --argjson eligible_tiers "$eligible_tiers" \
    '{"selected": $slug, "avg_score": $avg_score, "runs": $runs, "candidates_evaluated": $candidates_evaluated, "provider": $provider, "prompt_content_policy": $prompt_content_policy, "eligible_tiers": $eligible_tiers}'
}

# --- Action: evaluate ---
_action_evaluate() {
  local model_slug="${1:?Usage: fluxbench-challenger.sh evaluate <model-slug>}"

  _require_file "$MODEL_REGISTRY" "model registry"
  _require_file "$BUDGET_CONFIG" "budget config"

  # Read challenger config from budget.yaml (single subprocess)
  _budget_vals=$(python3 -c "
import yaml, os
with open(os.environ['BUDGET_CONFIG']) as f:
    d = yaml.safe_load(f) or {}
c = d.get('challenger', {})
print(c.get('promotion_threshold', 10))
print(c.get('early_exit_margin', 0.20))
print(c.get('stale_threshold', 20))
")
  promotion_threshold=$(echo "$_budget_vals" | sed -n '1p')
  early_exit_margin=$(echo "$_budget_vals" | sed -n '2p')
  stale_threshold=$(echo "$_budget_vals" | sed -n '3p')

  run_count=$(_count_runs "$model_slug")

  # Insufficient runs — not ready to evaluate
  if [[ "$run_count" -lt "$promotion_threshold" ]]; then
    # Check early exit: >= 5 runs AND all gates pass by > early_exit_margin
    if [[ "$run_count" -ge 5 ]] && [[ -f "$RESULTS_JSONL" ]]; then
      export _FB_SLUG="$model_slug"
      export _FB_EARLY_MARGIN="$early_exit_margin"
      export _FB_PROMO_THRESH="$promotion_threshold"

      early_exit=$(python3 -c "
import json, sys, os

slug = os.environ['_FB_SLUG']
results_path = os.environ['RESULTS_JSONL']
early_margin = float(os.environ['_FB_EARLY_MARGIN'])
promo_thresh = int(os.environ.get('_FB_PROMO_THRESH', '10'))

with open(results_path) as f:
    lines = [json.loads(l) for l in f if l.strip()]

model_runs = [r for r in lines if r.get('model_slug') == slug]
if not model_runs:
    print('false')
    sys.exit(0)

# Aggregate gate pass rates across recent runs
window = model_runs[-min(len(model_runs), promo_thresh):]

core_gates = [
    'fluxbench-format-compliance',
    'fluxbench-finding-recall',
    'fluxbench-false-positive-rate',
    'fluxbench-severity-accuracy',
    'fluxbench-persona-adherence',
]

gate_pass_rates = {}
for gate_name in core_gates:
    passes = 0
    total = 0
    for run in window:
        gates = run.get('gate_results', {})
        gate = gates.get(gate_name, {})
        passed = gate.get('passed')
        if passed is None:
            continue  # skip uncomputed gates
        total += 1
        if passed:
            passes += 1
    if total > 0:
        gate_pass_rates[gate_name] = passes / total

# All gates must pass >= 70% of the time
all_pass = all(rate >= 0.70 for rate in gate_pass_rates.values()) if gate_pass_rates else False

if not all_pass:
    print('false')
    sys.exit(0)

# Early-exit margin check: average metric values across window must exceed threshold by margin
all_pass_by_margin = True
for gate_name in core_gates:
    values = []
    thresholds = []
    for run in window:
        gates = run.get('gate_results', {})
        gate = gates.get(gate_name, {})
        value = gate.get('value')
        threshold = gate.get('threshold')
        if value is not None and threshold is not None:
            values.append(float(value))
            thresholds.append(float(threshold))
    if not values:
        continue  # skip uncomputed gates
    avg_value = sum(values) / len(values)
    avg_threshold = sum(thresholds) / len(thresholds)
    # Check margin: for higher-is-better, value should exceed threshold by margin
    # For lower-is-better (false_positive_rate), threshold should exceed value by margin
    if 'false-positive' in gate_name:
        margin = avg_threshold - avg_value
    else:
        margin = avg_value - avg_threshold
    if margin < early_margin:
        all_pass_by_margin = False
        break

print('true' if all_pass_by_margin else 'false')
" 2>&1)

      if [[ "$early_exit" == "true" ]]; then
        # Fast-track promote
        _promote_model "$model_slug" || { echo "Error: failed to promote $model_slug" >&2; return 1; }
        echo "Early exit: promoted $model_slug after $run_count runs" >&2
        jq -n \
          --arg slug "$model_slug" \
          --argjson runs "$run_count" \
          '{"verdict": "promoted", "reason": "early_exit", "model": $slug, "runs": $runs}'
        return 0
      fi
    fi

    # Not enough runs and no early exit
    jq -n \
      --arg slug "$model_slug" \
      --argjson runs "$run_count" \
      --argjson required "$promotion_threshold" \
      '{"verdict": "insufficient_runs", "model": $slug, "runs": $runs, "required": $required}'
    return 0
  fi

  # Enough runs: evaluate all 5 core gates
  if [[ ! -f "$RESULTS_JSONL" ]]; then
    jq -n \
      --arg slug "$model_slug" \
      '{"verdict": "insufficient_runs", "model": $slug, "runs": 0, "reason": "no results file"}'
    return 0
  fi

  export _FB_SLUG="$model_slug"
  export _FB_STALE="$stale_threshold"
  export _FB_PROMO_THRESH="$promotion_threshold"

  verdict=$(python3 -c "
import json, sys, os

slug = os.environ['_FB_SLUG']
results_path = os.environ['RESULTS_JSONL']
stale_threshold = int(os.environ['_FB_STALE'])
promo_thresh = int(os.environ.get('_FB_PROMO_THRESH', '10'))

with open(results_path) as f:
    lines = [json.loads(l) for l in f if l.strip()]

model_runs = [r for r in lines if r.get('model_slug') == slug]
run_count = len(model_runs)

if not model_runs:
    print(json.dumps({'verdict': 'failing', 'model': slug, 'runs': 0, 'failed_gates': []}))
    sys.exit(0)

# Aggregate gate pass rates across recent runs
window = model_runs[-min(len(model_runs), promo_thresh):]

core_gates = [
    'fluxbench-format-compliance',
    'fluxbench-finding-recall',
    'fluxbench-false-positive-rate',
    'fluxbench-severity-accuracy',
    'fluxbench-persona-adherence',
]

gate_pass_rates = {}
for gate_name in core_gates:
    passes = 0
    total = 0
    for run in window:
        gates = run.get('gate_results', {})
        gate = gates.get(gate_name, {})
        passed = gate.get('passed')
        if passed is None:
            continue  # skip uncomputed gates
        total += 1
        if passed:
            passes += 1
    if total > 0:
        gate_pass_rates[gate_name] = passes / total

# All gates must pass >= 70% of the time
all_pass = all(rate >= 0.70 for rate in gate_pass_rates.values()) if gate_pass_rates else False
failed_gates = [g for g, r in gate_pass_rates.items() if r < 0.70]

if all_pass:
    print(json.dumps({'verdict': 'promoted', 'model': slug, 'runs': run_count}))
else:
    if run_count > stale_threshold:
        print(json.dumps({'verdict': 'rejected', 'model': slug, 'runs': run_count, 'failed_gates': failed_gates}))
    else:
        print(json.dumps({'verdict': 'failing', 'model': slug, 'runs': run_count, 'failed_gates': failed_gates}))
")

  verdict_type=$(echo "$verdict" | jq -r '.verdict')

  # Update registry based on verdict
  if [[ "$verdict_type" == "promoted" ]]; then
    _promote_model "$model_slug" || { echo "Error: failed to promote $model_slug" >&2; return 1; }
    echo "Promoted $model_slug to qualified" >&2
  elif [[ "$verdict_type" == "rejected" ]]; then
    _set_model_status "$model_slug" "rejected" || { echo "Error: failed to reject $model_slug" >&2; return 1; }
    echo "Rejected $model_slug after exceeding stale threshold" >&2
  fi

  echo "$verdict"
}

# --- Action: status ---
_action_status() {
  _require_file "$MODEL_REGISTRY" "model registry"
  _require_file "$BUDGET_CONFIG" "budget config"

  # Read stale_threshold from budget config
  stale_threshold=$(python3 -c "
import yaml, os
with open(os.environ.get('BUDGET_CONFIG', '')) as f:
    budget = yaml.safe_load(f) or {}
print(budget.get('challenger', {}).get('stale_threshold', 20))
")

  # Find challenger model in registry
  challenger_slug=$(python3 -c "
import yaml, json, os

with open(os.environ.get('MODEL_REGISTRY', '')) as f:
    reg = yaml.safe_load(f) or {}

models = reg.get('models', {}) or {}
if isinstance(models, list):
    for m in models:
        if isinstance(m, dict) and m.get('status') == 'challenger':
            print(m.get('model_id', ''))
            exit(0)
else:
    for slug, m in models.items():
        if isinstance(m, dict) and m.get('status') == 'challenger':
            print(slug)
            exit(0)
print('')
")

  if [[ -z "$challenger_slug" ]]; then
    jq -n \
      --argjson max_runs "$stale_threshold" \
      '{"challenger": null, "runs": 0, "max_runs": $max_runs}'
    return 0
  fi

  run_count=$(_count_runs "$challenger_slug")
  jq -n \
    --arg slug "$challenger_slug" \
    --argjson runs "$run_count" \
    --argjson max_runs "$stale_threshold" \
    '{"challenger": $slug, "runs": $runs, "max_runs": $max_runs}'
}

# --- Dispatch ---
case "$action" in
  select)   _action_select ;;
  evaluate) _action_evaluate "$@" ;;
  status)   _action_status ;;
  *)
    echo "Error: unknown action '$action'" >&2
    echo "Usage: fluxbench-challenger.sh <select|evaluate|status>" >&2
    exit 1
    ;;
esac
