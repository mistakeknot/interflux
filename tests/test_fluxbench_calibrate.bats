#!/usr/bin/env bats
bats_require_minimum_version 1.5.0

setup() {
    SCRIPT_DIR="${BATS_TEST_DIRNAME}/../scripts"
    FIXTURES_DIR="${BATS_TEST_DIRNAME}/fixtures/qualification"
    TMPDIR_CAL="$(mktemp -d)"
    export FLUXBENCH_RESULTS_JSONL="${TMPDIR_CAL}/results.jsonl"
}

teardown() {
    rm -rf "$TMPDIR_CAL"
}

@test "calibrate.sh runs all fixtures and writes thresholds" {
    run bash "${SCRIPT_DIR}/fluxbench-calibrate.sh" --fixtures-dir "$FIXTURES_DIR" --output "$TMPDIR_CAL/thresholds.yaml" --mock
    [ "$status" -eq 0 ]
    [ -f "$TMPDIR_CAL/thresholds.yaml" ]
    count=$(python3 -c "import yaml; d=yaml.safe_load(open('$TMPDIR_CAL/thresholds.yaml')); print(len(d['thresholds']))")
    [ "$count" -eq 5 ]
}

@test "calibrate.sh source field says calibrated not defaults" {
    run bash "${SCRIPT_DIR}/fluxbench-calibrate.sh" --fixtures-dir "$FIXTURES_DIR" --output "$TMPDIR_CAL/thresholds.yaml" --mock
    [ "$status" -eq 0 ]
    source_val=$(python3 -c "import yaml; d=yaml.safe_load(open('$TMPDIR_CAL/thresholds.yaml')); print(d['source'])")
    [ "$source_val" = "calibrated" ]
}

@test "calibrate.sh without mode flag errors with message" {
    run bash "${SCRIPT_DIR}/fluxbench-calibrate.sh" --fixtures-dir "$FIXTURES_DIR" --output "$TMPDIR_CAL/thresholds.yaml"
    [ "$status" -ne 0 ]
    [[ "$output" == *"--mock"* ]] || [[ "$output" == *"--emit"* ]] || [[ "$output" == *"--score"* ]]
}
