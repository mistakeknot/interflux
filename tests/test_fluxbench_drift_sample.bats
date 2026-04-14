#!/usr/bin/env bats
bats_require_minimum_version 1.5.0

setup() {
    SCRIPT_DIR="${BATS_TEST_DIRNAME}/../scripts"
    TMPDIR_DS="$(mktemp -d)"
    export MODEL_REGISTRY="${TMPDIR_DS}/model-registry.yaml"
    export FLUXBENCH_RESULTS_JSONL="${TMPDIR_DS}/results.jsonl"
    export DRIFT_SAMPLE_COUNTER="${TMPDIR_DS}/drift-sample-counter"
    export METRICS_FILE="${TMPDIR_DS}/fluxbench-metrics.yaml"

    # Create minimal metrics config
    cat > "$METRICS_FILE" <<'YAML'
core_gates:
  fluxbench-finding-recall:
    higher_is_better: true
  fluxbench-false-positive-rate:
    higher_is_better: false
  fluxbench-severity-accuracy:
    higher_is_better: true
  fluxbench-format-compliance:
    higher_is_better: true
YAML

    # Create registry with one qualified model + baseline
    cat > "$MODEL_REGISTRY" <<'YAML'
fluxbench:
  sample_rate: 3
  max_sample_gap: 5
  drift_threshold: 0.15
  hysteresis_band: 0.05
  correlated_drift_threshold: 0.50
models:
  test-model:
    status: qualified
    drift_flagged: false
    qualified_baseline:
      fluxbench-finding-recall: 0.80
      fluxbench-false-positive-rate: 0.10
      fluxbench-severity-accuracy: 0.85
      fluxbench-format-compliance: 0.98
YAML

    # Create JSONL with matching scores (no drift)
    jq -cn '{model_slug: "test-model", metrics: {
      "fluxbench-finding-recall": 0.80,
      "fluxbench-false-positive-rate": 0.10,
      "fluxbench-severity-accuracy": 0.85,
      "fluxbench-format-compliance": 0.98
    }}' > "$FLUXBENCH_RESULTS_JSONL"
}

teardown() {
    rm -rf "$TMPDIR_DS"
}

@test "drift-sample.sh increments counter and skips below sample_rate" {
    run --separate-stderr bash "${SCRIPT_DIR}/fluxbench-drift-sample.sh"
    [ "$status" -eq 0 ]
    action=$(echo "$output" | jq -r '.action')
    [ "$action" = "skipped" ]
    counter=$(echo "$output" | jq -r '.counter')
    [ "$counter" -eq 1 ]
}

@test "drift-sample.sh triggers check when counter reaches sample_rate" {
    # Set counter to sample_rate (will trigger on next call)
    echo "3" > "$DRIFT_SAMPLE_COUNTER"
    run --separate-stderr bash "${SCRIPT_DIR}/fluxbench-drift-sample.sh"
    [ "$status" -eq 0 ]
    action=$(echo "$output" | jq -r '.action')
    [ "$action" = "sampled" ]
    # Counter should be reset to 0
    counter=$(cat "$DRIFT_SAMPLE_COUNTER")
    [ "$counter" -eq 0 ]
}

@test "drift-sample.sh forces check on max_sample_gap" {
    # Set counter to max_sample_gap (5)
    echo "5" > "$DRIFT_SAMPLE_COUNTER"
    run --separate-stderr bash "${SCRIPT_DIR}/fluxbench-drift-sample.sh"
    [ "$status" -eq 0 ]
    action=$(echo "$output" | jq -r '.action')
    [ "$action" = "sampled" ]
}

@test "drift-sample.sh --force bypasses counter" {
    echo "0" > "$DRIFT_SAMPLE_COUNTER"
    run --separate-stderr bash "${SCRIPT_DIR}/fluxbench-drift-sample.sh" --force
    [ "$status" -eq 0 ]
    action=$(echo "$output" | jq -r '.action')
    [ "$action" = "sampled" ]
    reason=$(echo "$output" | jq -r '.reason')
    [ "$reason" = "forced" ]
}

@test "drift-sample.sh reports no_qualified_models when none qualified" {
    cat > "$MODEL_REGISTRY" <<'YAML'
fluxbench:
  sample_rate: 1
models:
  test-model:
    status: candidate
YAML
    run --separate-stderr bash "${SCRIPT_DIR}/fluxbench-drift-sample.sh" --force
    [ "$status" -eq 0 ]
    action=$(echo "$output" | jq -r '.action')
    [ "$action" = "no_qualified_models" ]
}

@test "drift-sample.sh detects no drift when scores match baseline" {
    run --separate-stderr bash "${SCRIPT_DIR}/fluxbench-drift-sample.sh" --force
    [ "$status" -eq 0 ]
    drift_count=$(echo "$output" | jq -r '.drift_count')
    [ "$drift_count" -eq 0 ]
    fleet_verdict=$(echo "$output" | jq -r '.fleet_verdict')
    [ "$fleet_verdict" = "no_drift" ]
}

@test "drift-sample.sh detects drift with degraded scores" {
    # Replace JSONL with degraded scores (recall dropped from 0.80 to 0.50)
    jq -cn '{model_slug: "test-model", metrics: {
      "fluxbench-finding-recall": 0.50,
      "fluxbench-false-positive-rate": 0.10,
      "fluxbench-severity-accuracy": 0.85,
      "fluxbench-format-compliance": 0.98
    }}' > "$FLUXBENCH_RESULTS_JSONL"

    run --separate-stderr bash "${SCRIPT_DIR}/fluxbench-drift-sample.sh" --force
    [ "$status" -eq 0 ]
    drift_count=$(echo "$output" | jq -r '.drift_count')
    [ "$drift_count" -eq 1 ]
    echo "$output" | jq -e '.drifted_models[] | select(. == "test-model")'
}

@test "drift-sample.sh counter uses atomic writes" {
    # Verify tmp+mv pattern — counter file should never be empty
    for i in $(seq 1 5); do
        bash "${SCRIPT_DIR}/fluxbench-drift-sample.sh" >/dev/null 2>&1 &
    done
    wait
    # Counter file should exist and contain a valid number
    [ -f "$DRIFT_SAMPLE_COUNTER" ]
    counter=$(cat "$DRIFT_SAMPLE_COUNTER")
    [[ "$counter" =~ ^[0-9]+$ ]]
}
