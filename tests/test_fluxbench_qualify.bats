#!/usr/bin/env bats
bats_require_minimum_version 1.5.0

setup() {
    SCRIPT_DIR="${BATS_TEST_DIRNAME}/../scripts"
    FIXTURES_DIR="${BATS_TEST_DIRNAME}/fixtures/qualification"
    TMPDIR_QUAL="$(mktemp -d)"
    export FLUXBENCH_RESULTS_JSONL="${TMPDIR_QUAL}/results.jsonl"
    export MODEL_REGISTRY="${TMPDIR_QUAL}/model-registry.yaml"
    # Create minimal registry
    cat > "$MODEL_REGISTRY" <<'YAML'
fluxbench:
  sample_rate: 10
  drift_threshold: 0.15
  hysteresis_band: 0.05
  correlated_drift_threshold: 0.50
  challenger_slots: 1
  weekly_budget_ceiling: 5

models:
  test-model:
    status: candidate
    qualified_baseline: null
    fluxbench:
      format_compliance: null
      finding_recall: null
      false_positive_rate: null
      severity_accuracy: null
      persona_adherence: null
YAML
}

teardown() {
    rm -rf "$TMPDIR_QUAL"
}

@test "qualify.sh promotes model to auto-qualified in mock mode" {
    run bash "${SCRIPT_DIR}/fluxbench-qualify.sh" "test-model" --mock --fixtures-dir "$FIXTURES_DIR"
    [ "$status" -eq 0 ]
    status_val=$(python3 -c "import yaml; d=yaml.safe_load(open('$MODEL_REGISTRY')); print(d['models']['test-model']['status'])")
    [ "$status_val" = "auto-qualified" ]
}

@test "qualify.sh sets qualified_baseline on first qualification" {
    run bash "${SCRIPT_DIR}/fluxbench-qualify.sh" "test-model" --mock --fixtures-dir "$FIXTURES_DIR"
    [ "$status" -eq 0 ]
    baseline=$(python3 -c "import yaml; d=yaml.safe_load(open('$MODEL_REGISTRY')); print(d['models']['test-model']['qualified_baseline'] is not None)")
    [ "$baseline" = "True" ]
}

@test "qualify.sh does not overwrite existing qualified_baseline" {
    # Set an existing baseline
    python3 -c "
import yaml
with open('$MODEL_REGISTRY') as f: d = yaml.safe_load(f)
d['models']['test-model']['qualified_baseline'] = {'fluxbench-finding-recall': 0.99}
with open('$MODEL_REGISTRY', 'w') as f: yaml.dump(d, f, default_flow_style=False)
"
    run bash "${SCRIPT_DIR}/fluxbench-qualify.sh" "test-model" --mock --fixtures-dir "$FIXTURES_DIR"
    [ "$status" -eq 0 ]
    # Baseline should still have the original value
    recall=$(python3 -c "import yaml; d=yaml.safe_load(open('$MODEL_REGISTRY')); print(d['models']['test-model']['qualified_baseline']['fluxbench-finding-recall'])")
    [ "$recall" = "0.99" ]
}

@test "qualify.sh without mode flag errors" {
    run bash "${SCRIPT_DIR}/fluxbench-qualify.sh" "test-model" --fixtures-dir "$FIXTURES_DIR"
    [ "$status" -ne 0 ]
    [[ "$output" == *"--mock"* ]] || [[ "$output" == *"--emit"* ]] || [[ "$output" == *"--score"* ]]
}

@test "qualify.sh writes results to JSONL" {
    run bash "${SCRIPT_DIR}/fluxbench-qualify.sh" "test-model" --mock --fixtures-dir "$FIXTURES_DIR"
    [ "$status" -eq 0 ]
    [ -f "$FLUXBENCH_RESULTS_JSONL" ]
    lines=$(wc -l < "$FLUXBENCH_RESULTS_JSONL")
    [ "$lines" -ge 5 ]
}
