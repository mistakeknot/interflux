#!/usr/bin/env bats
# Tests for flux-dispatch.sh — mechanical concurrency cap / admission control (issue #5).

bats_require_minimum_version 1.5.0

setup() {
    SCRIPT="$BATS_TEST_DIRNAME/../scripts/flux-dispatch.sh"
    OUTPUT_DIR="$(mktemp -d)"
}

teardown() {
    [[ -d "$OUTPUT_DIR" ]] && rm -rf "$OUTPUT_DIR"
}

@test "reset initializes in-flight count to zero" {
    run bash "$SCRIPT" reset "$OUTPUT_DIR" 3
    [[ "$status" -eq 0 ]]
    run bash "$SCRIPT" count "$OUTPUT_DIR"
    [[ "$status" -eq 0 ]]
    [[ "$output" == "0" ]]
}

@test "acquire increments the in-flight count" {
    bash "$SCRIPT" reset "$OUTPUT_DIR" 3
    bash "$SCRIPT" acquire "$OUTPUT_DIR" 3
    run bash "$SCRIPT" count "$OUTPUT_DIR"
    [[ "$output" == "1" ]]
    bash "$SCRIPT" acquire "$OUTPUT_DIR" 3
    run bash "$SCRIPT" count "$OUTPUT_DIR"
    [[ "$output" == "2" ]]
}

@test "acquire blocks/times out once the cap is reached (cap is enforced)" {
    bash "$SCRIPT" reset "$OUTPUT_DIR" 2
    bash "$SCRIPT" acquire "$OUTPUT_DIR" 2
    bash "$SCRIPT" acquire "$OUTPUT_DIR" 2
    # Cap is 2 and 2 are in flight — the next acquire must NOT succeed.
    run bash "$SCRIPT" acquire "$OUTPUT_DIR" 2 1
    [[ "$status" -eq 1 ]]
    # Count never breached the cap.
    run bash "$SCRIPT" count "$OUTPUT_DIR"
    [[ "$output" == "2" ]]
}

@test "release frees a slot so a blocked acquire can proceed" {
    bash "$SCRIPT" reset "$OUTPUT_DIR" 1
    bash "$SCRIPT" acquire "$OUTPUT_DIR" 1
    # Full — acquire would block. Free one and try again.
    bash "$SCRIPT" release "$OUTPUT_DIR"
    run bash "$SCRIPT" acquire "$OUTPUT_DIR" 1 2
    [[ "$status" -eq 0 ]]
    run bash "$SCRIPT" count "$OUTPUT_DIR"
    [[ "$output" == "1" ]]
}

@test "release never drops below zero" {
    bash "$SCRIPT" reset "$OUTPUT_DIR" 3
    bash "$SCRIPT" release "$OUTPUT_DIR"
    bash "$SCRIPT" release "$OUTPUT_DIR"
    run bash "$SCRIPT" count "$OUTPUT_DIR"
    [[ "$output" == "0" ]]
}

@test "wait releases a slot when the agent .md appears" {
    bash "$SCRIPT" reset "$OUTPUT_DIR" 3
    bash "$SCRIPT" acquire "$OUTPUT_DIR" 3
    ( sleep 1; touch "$OUTPUT_DIR/fd-safety.md" ) &
    run bash "$SCRIPT" wait "$OUTPUT_DIR" "$OUTPUT_DIR/fd-safety.md" 3 5
    [[ "$status" -eq 0 ]]
    run bash "$SCRIPT" count "$OUTPUT_DIR"
    [[ "$output" == "0" ]]
}

@test "wait releases the slot even on timeout (no permanent slot leak)" {
    bash "$SCRIPT" reset "$OUTPUT_DIR" 3
    bash "$SCRIPT" acquire "$OUTPUT_DIR" 3
    # File never appears — wait should time out (exit 1) but still release.
    run bash "$SCRIPT" wait "$OUTPUT_DIR" "$OUTPUT_DIR/never.md" 3 1
    [[ "$status" -eq 1 ]]
    run bash "$SCRIPT" count "$OUTPUT_DIR"
    [[ "$output" == "0" ]]
}

@test "concurrent acquires never exceed the cap" {
    bash "$SCRIPT" reset "$OUTPUT_DIR" 3
    # Fire 8 acquires in parallel against a cap of 3, each with a short timeout.
    for i in $(seq 1 8); do
        ( bash "$SCRIPT" acquire "$OUTPUT_DIR" 3 1 >/dev/null 2>&1 ) &
    done
    wait
    # No release happened, so exactly the cap should be claimed — never more.
    run bash "$SCRIPT" count "$OUTPUT_DIR"
    [[ "$output" -le 3 ]]
    [[ "$output" -eq 3 ]]
}

@test "env MAX_CONCURRENT_AGENTS overrides budget default" {
    run env MAX_CONCURRENT_AGENTS=2 bash "$SCRIPT" reset "$OUTPUT_DIR"
    [[ "$status" -eq 0 ]]
    [[ "$output" == "ok 0/2" ]]
}

@test "resolves cap from budget.yaml dispatch section when no arg/env" {
    run bash "$SCRIPT" reset "$OUTPUT_DIR"
    [[ "$status" -eq 0 ]]
    # budget.yaml ships dispatch.max_concurrent_agents: 6
    [[ "$output" == "ok 0/6" ]]
}
