#!/usr/bin/env bats

setup() {
    SCRIPT_DIR="${BATS_TEST_DIRNAME}/../scripts"
    TMPDIR_DRIFT="$(mktemp -d)"
    export MODEL_REGISTRY="${TMPDIR_DRIFT}/model-registry.yaml"
    # Create minimal registry with one qualified model
    cat > "$MODEL_REGISTRY" <<'YAML'
fluxbench:
  drift_threshold: 0.15
  hysteresis_band: 0.05
  correlated_drift_threshold: 0.50

models:
  test-model:
    status: qualified
    drift_flagged: false
    qualified_baseline:
      fluxbench-format-compliance: 0.98
      fluxbench-finding-recall: 0.80
      fluxbench-false-positive-rate: 0.10
      fluxbench-severity-accuracy: 0.85
      fluxbench-persona-adherence: 0.70
YAML
}

teardown() {
    rm -rf "$TMPDIR_DRIFT"
}

_make_shadow_result() {
    local fc="${1:-0.98}" fr="${2:-0.80}" fpr="${3:-0.10}" sa="${4:-0.85}" pa="${5:-0.70}"
    jq -n --arg fc "$fc" --arg fr "$fr" --arg fpr "$fpr" --arg sa "$sa" --arg pa "$pa" '{
        metrics: {
            "fluxbench-format-compliance": ($fc|tonumber),
            "fluxbench-finding-recall": ($fr|tonumber),
            "fluxbench-false-positive-rate": ($fpr|tonumber),
            "fluxbench-severity-accuracy": ($sa|tonumber),
            "fluxbench-persona-adherence": ($pa|tonumber)
        }
    }'
}

@test "drift.sh reports no_drift when scores match baseline" {
    _make_shadow_result 0.98 0.80 0.10 0.85 0.70 > "${TMPDIR_DRIFT}/shadow.json"
    run bash "${SCRIPT_DIR}/fluxbench-drift.sh" "test-model" "${TMPDIR_DRIFT}/shadow.json"
    [ "$status" -eq 0 ]
    verdict=$(echo "$output" | jq -r '.verdict')
    [ "$verdict" = "no_drift" ]
}

@test "drift.sh detects drift when recall drops >15%" {
    _make_shadow_result 0.98 0.60 0.10 0.85 0.70 > "${TMPDIR_DRIFT}/shadow.json"
    run bash "${SCRIPT_DIR}/fluxbench-drift.sh" "test-model" "${TMPDIR_DRIFT}/shadow.json"
    [ "$status" -eq 0 ]
    verdict=$(echo "$output" | jq -r '.verdict')
    [ "$verdict" = "drift_detected" ]
    # Check that finding-recall is in drifted metrics
    echo "$output" | jq -e '.drifted_metrics[] | select(. == "fluxbench-finding-recall")'
}

@test "drift.sh detects drift when false-positive-rate increases >15%" {
    # FPR is higher_is_better: false, so increase = bad
    _make_shadow_result 0.98 0.80 0.30 0.85 0.70 > "${TMPDIR_DRIFT}/shadow.json"
    run bash "${SCRIPT_DIR}/fluxbench-drift.sh" "test-model" "${TMPDIR_DRIFT}/shadow.json"
    [ "$status" -eq 0 ]
    verdict=$(echo "$output" | jq -r '.verdict')
    [ "$verdict" = "drift_detected" ]
}

@test "drift.sh clears drift when within hysteresis band" {
    # Set model as previously drifted
    python3 -c "
import yaml
with open('$MODEL_REGISTRY') as f: d = yaml.safe_load(f)
d['models']['test-model']['drift_flagged'] = True
with open('$MODEL_REGISTRY', 'w') as f: yaml.dump(d, f, default_flow_style=False)
"
    # Scores within 0.05 of baseline
    _make_shadow_result 0.96 0.78 0.12 0.83 0.68 > "${TMPDIR_DRIFT}/shadow.json"
    run bash "${SCRIPT_DIR}/fluxbench-drift.sh" "test-model" "${TMPDIR_DRIFT}/shadow.json"
    [ "$status" -eq 0 ]
    verdict=$(echo "$output" | jq -r '.verdict')
    [ "$verdict" = "drift_cleared" ]
}

@test "drift.sh fleet-check detects baseline shift" {
    # Add another model that's also drifted
    python3 -c "
import yaml
with open('$MODEL_REGISTRY') as f: d = yaml.safe_load(f)
d['models']['test-model']['drift_flagged'] = True
d['models']['model-2'] = {
    'status': 'qualified', 'drift_flagged': True,
    'qualified_baseline': {
        'fluxbench-format-compliance': 0.95,
        'fluxbench-finding-recall': 0.75,
        'fluxbench-false-positive-rate': 0.15,
        'fluxbench-severity-accuracy': 0.80,
        'fluxbench-persona-adherence': 0.65
    }
}
with open('$MODEL_REGISTRY', 'w') as f: yaml.dump(d, f, default_flow_style=False)
"
    # Both models drifted = 100% > 50% threshold
    _make_shadow_result 0.98 0.60 0.10 0.85 0.70 > "${TMPDIR_DRIFT}/shadow.json"
    run bash "${SCRIPT_DIR}/fluxbench-drift.sh" "test-model" "${TMPDIR_DRIFT}/shadow.json" --fleet-check
    [ "$status" -eq 0 ]
    verdict=$(echo "$output" | jq -r '.verdict')
    [ "$verdict" = "baseline_shift_suspected" ]
}
