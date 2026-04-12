#!/usr/bin/env bats
bats_require_minimum_version 1.5.0

setup() {
    SCRIPT_DIR="${BATS_TEST_DIRNAME}/../scripts"
    TMPDIR_SYNC="$(mktemp -d)"
    export FLUXBENCH_RESULTS_JSONL="${TMPDIR_SYNC}/results.jsonl"
    export AGMODB_REPO_PATH="${TMPDIR_SYNC}/agmodb"
    mkdir -p "$AGMODB_REPO_PATH"
}

teardown() {
    rm -rf "$TMPDIR_SYNC"
}

_write_result() {
    local model="$1" run_id="$2"
    jq -n --arg m "$model" --arg r "$run_id" '{
        model_slug:$m, qualification_run_id:$r,
        timestamp:"2026-04-07T00:00:00Z",
        metrics:{"fluxbench-format-compliance":0.95,"fluxbench-finding-recall":0.80,
                 "fluxbench-false-positive-rate":0.10,"fluxbench-severity-accuracy":0.75,
                 "fluxbench-persona-adherence":null},
        overall_pass:true
    }' >> "$FLUXBENCH_RESULTS_JSONL"
}

@test "sync.sh creates AgMoDB files from results" {
    _write_result "claude-sonnet" "qr-001"
    run bash "${SCRIPT_DIR}/fluxbench-sync.sh"
    [ "$status" -eq 0 ]
    [ -f "${AGMODB_REPO_PATH}/claude-sonnet.json" ]
    run jq -r '.model_slug' "${AGMODB_REPO_PATH}/claude-sonnet.json"
    [ "$output" = "claude-sonnet" ]
}

@test "sync.sh is idempotent — re-run does not duplicate" {
    _write_result "claude-sonnet" "qr-001"
    bash "${SCRIPT_DIR}/fluxbench-sync.sh"
    bash "${SCRIPT_DIR}/fluxbench-sync.sh"
    # Should still have exactly one file, not duplicated
    count=$(ls "${AGMODB_REPO_PATH}/"*.json 2>/dev/null | wc -l)
    [ "$count" -eq 1 ]
}

@test "sync.sh handles missing JSONL gracefully" {
    rm -f "$FLUXBENCH_RESULTS_JSONL"
    run bash "${SCRIPT_DIR}/fluxbench-sync.sh"
    [ "$status" -eq 0 ]
    [[ "$output" == *"No results"* ]] || [[ "$output" == *"nothing to sync"* ]] || [ -z "$output" ]
}

@test "sync.sh syncs multiple models" {
    _write_result "model-a" "qr-a1"
    _write_result "model-b" "qr-b1"
    run bash "${SCRIPT_DIR}/fluxbench-sync.sh"
    [ "$status" -eq 0 ]
    [ -f "${AGMODB_REPO_PATH}/model-a.json" ]
    [ -f "${AGMODB_REPO_PATH}/model-b.json" ]
}

@test "sync.sh dry-run does not write files" {
    _write_result "claude-sonnet" "qr-001"
    run bash "${SCRIPT_DIR}/fluxbench-sync.sh" --dry-run
    [ "$status" -eq 0 ]
    [ ! -f "${AGMODB_REPO_PATH}/claude-sonnet.json" ]
}
