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

# Atomic registry write under flock fd 201
# Caller exports env vars consumed by the python snippet passed as $1
_registry_write() {
  local py_snippet="$1"
  (
    flock -x 201
    python3 -c "
import yaml, json, sys, os

reg_path = os.environ['MODEL_REGISTRY']

with open(reg_path) as f:
    reg = yaml.safe_load(f) or {}

if 'models' not in reg or reg['models'] is None:
    reg['models'] = {}

${py_snippet}

with open(reg_path, 'w') as f:
    yaml.dump(reg, f, default_flow_style=False, sort_keys=False)
"
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
    'candidates_evaluated': len(candidates)
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
  export _FB_SLUG="$selected"
  _registry_write "
slug = os.environ['_FB_SLUG']
model = reg['models'].get(slug) if isinstance(reg['models'], dict) else None
if model is None and isinstance(reg['models'], list):
    for m in reg['models']:
        if isinstance(m, dict) and m.get('model_id', '') == slug:
            model = m
            break
if model is not None:
    model['status'] = 'challenger'
"

  echo "Challenger selected: $selected" >&2

  avg_score=$(echo "$result" | jq -r '.avg_score')
  candidates_evaluated=$(echo "$result" | jq -r '.candidates_evaluated')
  jq -n \
    --arg slug "$selected" \
    --argjson avg_score "$avg_score" \
    --argjson runs "$run_count" \
    --argjson candidates_evaluated "$candidates_evaluated" \
    '{"selected": $slug, "avg_score": $avg_score, "runs": $runs, "candidates_evaluated": $candidates_evaluated}'
}

# --- Action: evaluate ---
_action_evaluate() {
  local model_slug="${1:?Usage: fluxbench-challenger.sh evaluate <model-slug>}"

  _require_file "$MODEL_REGISTRY" "model registry"
  _require_file "$BUDGET_CONFIG" "budget config"

  # Read challenger config from budget.yaml (no eval — direct reads)
  promotion_threshold=$(python3 -c "import yaml,os; d=yaml.safe_load(open(os.environ['BUDGET_CONFIG'])) or {}; print(d.get('challenger',{}).get('promotion_threshold',10))")
  early_exit_margin=$(python3 -c "import yaml,os; d=yaml.safe_load(open(os.environ['BUDGET_CONFIG'])) or {}; print(d.get('challenger',{}).get('early_exit_margin',0.20))")
  stale_threshold=$(python3 -c "import yaml,os; d=yaml.safe_load(open(os.environ['BUDGET_CONFIG'])) or {}; print(d.get('challenger',{}).get('stale_threshold',20))")

  run_count=$(_count_runs "$model_slug")

  # Insufficient runs — not ready to evaluate
  if [[ "$run_count" -lt "$promotion_threshold" ]]; then
    # Check early exit: >= 5 runs AND all gates pass by > early_exit_margin
    if [[ "$run_count" -ge 5 ]] && [[ -f "$RESULTS_JSONL" ]]; then
      export _FB_SLUG="$model_slug"
      export _FB_EARLY_MARGIN="$early_exit_margin"

      early_exit=$(python3 -c "
import json, sys, os

slug = os.environ['_FB_SLUG']
results_path = os.environ['RESULTS_JSONL']
early_margin = float(os.environ['_FB_EARLY_MARGIN'])

with open(results_path) as f:
    lines = [json.loads(l) for l in f if l.strip()]

model_runs = [r for r in lines if r.get('model_slug') == slug]
if not model_runs:
    print('false')
    sys.exit(0)

# Check all 5 core gate results across recent runs
# Use the most recent run's gate_results
latest = model_runs[-1]
gates = latest.get('gate_results', {})

core_gates = [
    'fluxbench-format-compliance',
    'fluxbench-finding-recall',
    'fluxbench-false-positive-rate',
    'fluxbench-severity-accuracy',
    'fluxbench-persona-adherence',
]

all_pass_by_margin = True
for gate_name in core_gates:
    gate = gates.get(gate_name, {})
    value = gate.get('value')
    threshold = gate.get('threshold')
    passed = gate.get('passed')
    if value is None or threshold is None or passed is None:
        continue  # skip uncomputed gates
    if not passed:
        all_pass_by_margin = False
        break
    # Check margin: for higher-is-better, value should exceed threshold by margin
    # For lower-is-better (false_positive_rate), threshold should exceed value by margin
    if 'false-positive' in gate_name:
        margin = float(threshold) - float(value)
    else:
        margin = float(value) - float(threshold)
    if margin < early_margin:
        all_pass_by_margin = False
        break

print('true' if all_pass_by_margin else 'false')
" 2>&1)

      if [[ "$early_exit" == "true" ]]; then
        # Fast-track promote
        _registry_write "
slug = os.environ['_FB_SLUG']
model = reg['models'].get(slug) if isinstance(reg['models'], dict) else None
if model is None and isinstance(reg['models'], list):
    for m in reg['models']:
        if isinstance(m, dict) and m.get('model_id', '') == slug:
            model = m
            break
if model is not None:
    model['status'] = 'qualified'
"
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

  verdict=$(python3 -c "
import json, sys, os

slug = os.environ['_FB_SLUG']
results_path = os.environ['RESULTS_JSONL']
stale_threshold = int(os.environ['_FB_STALE'])

with open(results_path) as f:
    lines = [json.loads(l) for l in f if l.strip()]

model_runs = [r for r in lines if r.get('model_slug') == slug]
run_count = len(model_runs)

# Check all core gates across recent runs (use latest)
latest = model_runs[-1] if model_runs else {}
gates = latest.get('gate_results', {})

core_gates = [
    'fluxbench-format-compliance',
    'fluxbench-finding-recall',
    'fluxbench-false-positive-rate',
    'fluxbench-severity-accuracy',
    'fluxbench-persona-adherence',
]

all_pass = True
failed_gates = []
for gate_name in core_gates:
    gate = gates.get(gate_name, {})
    passed = gate.get('passed')
    if passed is None:
        continue  # skip uncomputed gates (e.g., persona-adherence)
    if not passed:
        all_pass = False
        failed_gates.append(gate_name)

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
    _registry_write "
slug = os.environ['_FB_SLUG']
model = reg['models'].get(slug) if isinstance(reg['models'], dict) else None
if model is None and isinstance(reg['models'], list):
    for m in reg['models']:
        if isinstance(m, dict) and m.get('model_id', '') == slug:
            model = m
            break
if model is not None:
    model['status'] = 'qualified'
"
    echo "Promoted $model_slug to qualified" >&2
  elif [[ "$verdict_type" == "rejected" ]]; then
    _registry_write "
slug = os.environ['_FB_SLUG']
model = reg['models'].get(slug) if isinstance(reg['models'], dict) else None
if model is None and isinstance(reg['models'], list):
    for m in reg['models']:
        if isinstance(m, dict) and m.get('model_id', '') == slug:
            model = m
            break
if model is not None:
    model['status'] = 'rejected'
"
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
