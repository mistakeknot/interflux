#!/usr/bin/env bats
# Tests for flux-backoff.sh — transient-failure backpressure (issue #9).
# Covers: transient-vs-terminal-vs-unknown classification, exponential-backoff
# timing/jitter bounds, multiplicative concurrency decrease + additive recovery,
# and that flux-dispatch.sh acquire honors the decreased cap.

bats_require_minimum_version 1.5.0

setup() {
    BACKOFF="$BATS_TEST_DIRNAME/../scripts/flux-backoff.sh"
    DISPATCH="$BATS_TEST_DIRNAME/../scripts/flux-dispatch.sh"
    OUTPUT_DIR="$(mktemp -d)"
}

teardown() {
    [[ -d "$OUTPUT_DIR" ]] && rm -rf "$OUTPUT_DIR"
}

# --- classification -------------------------------------------------------

@test "classify: HTTP 429 is transient" {
    run bash -c "echo 'API Error 429 Too Many Requests' | '$BACKOFF' classify"
    [[ "$status" -eq 0 ]]
    [[ "$output" == "transient" ]]
}

@test "classify: rate_limit_error is transient" {
    run bash -c "echo 'rate_limit_error: please slow down' | '$BACKOFF' classify"
    [[ "$output" == "transient" ]]
}

@test "classify: overloaded_error is transient" {
    run bash -c "echo 'overloaded_error' | '$BACKOFF' classify"
    [[ "$output" == "transient" ]]
}

@test "classify: 503/529 service errors are transient" {
    run bash -c "echo 'HTTP 529 overloaded' | '$BACKOFF' classify"
    [[ "$output" == "transient" ]]
    run bash -c "echo 'Error: HTTP 503 Service Unavailable' | '$BACKOFF' classify"
    [[ "$output" == "transient" ]]
}

@test "classify: Usage-Policy refusal is terminal, not transient" {
    msg='API Error: Claude Code is unable to respond to this request, which appears to violate our Usage Policy'
    run bash -c "echo '$msg' | '$BACKOFF' classify"
    [[ "$status" -eq 0 ]]
    [[ "$output" == "terminal" ]]
}

@test "classify: crash/other is unknown" {
    run bash -c "echo 'segmentation fault (core dumped)' | '$BACKOFF' classify"
    [[ "$output" == "unknown" ]]
}

@test "classify: reads from a file argument" {
    echo "rate limit exceeded" > "$OUTPUT_DIR/err.txt"
    run bash "$BACKOFF" classify "$OUTPUT_DIR/err.txt"
    [[ "$output" == "transient" ]]
}

@test "classify: a year like 4290 does not false-positive as 429" {
    run bash -c "echo 'completed at 4290 tokens' | '$BACKOFF' classify"
    [[ "$output" == "unknown" ]]
}

# --- backoff timing / jitter bounds --------------------------------------

@test "delay: attempt 1 window is bounded by base_delay" {
    # base=2 -> attempt 1 window is 2, full jitter picks in [0,2].
    for _ in 1 2 3 4 5 6 7 8; do
        run env FLUX_BACKOFF_BASE_DELAY=2 FLUX_BACKOFF_MAX_DELAY=60 bash "$BACKOFF" delay 1
        [[ "$status" -eq 0 ]]
        [[ "$output" -ge 0 ]]
        [[ "$output" -le 2 ]]
    done
}

@test "delay: window grows exponentially but is capped at max_delay" {
    # base=2 factor=2 -> attempt 6 raw window = 2*2^5 = 64, capped at max=10.
    for _ in 1 2 3 4 5 6 7 8; do
        run env FLUX_BACKOFF_BASE_DELAY=2 FLUX_BACKOFF_FACTOR=2 FLUX_BACKOFF_MAX_DELAY=10 bash "$BACKOFF" delay 6
        [[ "$output" -ge 0 ]]
        [[ "$output" -le 10 ]]
    done
}

@test "delay: full jitter actually varies across calls" {
    seen=""
    for _ in $(seq 1 20); do
        d=$(env FLUX_BACKOFF_BASE_DELAY=8 FLUX_BACKOFF_MAX_DELAY=60 bash "$BACKOFF" delay 4)
        seen="$seen $d"
    done
    # At least two distinct values must appear (jitter is not constant).
    distinct=$(echo $seen | tr ' ' '\n' | sort -u | wc -l)
    [[ "$distinct" -ge 2 ]]
}

@test "sleep: returns the delay and waits at least 0s, at most window" {
    start=$(date +%s)
    run env FLUX_BACKOFF_BASE_DELAY=2 FLUX_BACKOFF_MAX_DELAY=2 bash "$BACKOFF" sleep 1
    end=$(date +%s)
    [[ "$status" -eq 0 ]]
    [[ "$output" -ge 0 ]]
    [[ "$output" -le 2 ]]
    [[ $((end - start)) -le 3 ]]
}

# --- multiplicative decrease / additive increase -------------------------

@test "decrease: halves the effective cap (6 -> 3 -> 2 -> 1), floored" {
    bash "$DISPATCH" reset "$OUTPUT_DIR" 6 >/dev/null
    run bash "$BACKOFF" decrease "$OUTPUT_DIR" 6
    [[ "$output" == "3" ]]
    run bash "$BACKOFF" decrease "$OUTPUT_DIR" 6
    [[ "$output" == "2" ]]
    run bash "$BACKOFF" decrease "$OUTPUT_DIR" 6
    [[ "$output" == "1" ]]
    # Floor: never below min_effective_cap (default 1).
    run bash "$BACKOFF" decrease "$OUTPUT_DIR" 6
    [[ "$output" == "1" ]]
}

@test "decrease: respects FLUX_BACKOFF_MIN_CAP floor" {
    bash "$DISPATCH" reset "$OUTPUT_DIR" 8 >/dev/null
    run env FLUX_BACKOFF_MIN_CAP=2 bash "$BACKOFF" decrease "$OUTPUT_DIR" 8  # 8->4
    [[ "$output" == "4" ]]
    run env FLUX_BACKOFF_MIN_CAP=2 bash "$BACKOFF" decrease "$OUTPUT_DIR" 8  # 4->2
    [[ "$output" == "2" ]]
    run env FLUX_BACKOFF_MIN_CAP=2 bash "$BACKOFF" decrease "$OUTPUT_DIR" 8  # floored at 2
    [[ "$output" == "2" ]]
}

@test "effective: reports min(base, congestion cap)" {
    bash "$DISPATCH" reset "$OUTPUT_DIR" 6 >/dev/null
    run bash "$BACKOFF" effective "$OUTPUT_DIR" 6
    [[ "$output" == "6" ]]   # no congestion cap yet
    bash "$BACKOFF" decrease "$OUTPUT_DIR" 6 >/dev/null  # cap -> 3
    run bash "$BACKOFF" effective "$OUTPUT_DIR" 6
    [[ "$output" == "3" ]]
}

@test "increase: additively recovers and clears the cap at base" {
    bash "$DISPATCH" reset "$OUTPUT_DIR" 6 >/dev/null
    bash "$BACKOFF" decrease "$OUTPUT_DIR" 6 >/dev/null  # 3
    bash "$BACKOFF" decrease "$OUTPUT_DIR" 6 >/dev/null  # 2
    run bash "$BACKOFF" increase "$OUTPUT_DIR" 6
    [[ "$output" == "3" ]]
    run bash "$BACKOFF" increase "$OUTPUT_DIR" 6
    [[ "$output" == "4" ]]
    run bash "$BACKOFF" increase "$OUTPUT_DIR" 6  # 5
    run bash "$BACKOFF" increase "$OUTPUT_DIR" 6  # reaches base -> clears file, prints base
    [[ "$output" == "6" ]]
    [[ ! -e "$OUTPUT_DIR/.dispatch-cap" ]]
}

@test "reset (dispatch) clears a stale congestion cap from a prior run" {
    bash "$DISPATCH" reset "$OUTPUT_DIR" 6 >/dev/null
    bash "$BACKOFF" decrease "$OUTPUT_DIR" 6 >/dev/null
    [[ -e "$OUTPUT_DIR/.dispatch-cap" ]]
    bash "$DISPATCH" reset "$OUTPUT_DIR" 6 >/dev/null
    [[ ! -e "$OUTPUT_DIR/.dispatch-cap" ]]
}

# --- composition: acquire honors the decreased cap -----------------------

@test "acquire blocks at the decreased cap (backpressure engages)" {
    bash "$DISPATCH" reset "$OUTPUT_DIR" 6 >/dev/null
    bash "$BACKOFF" decrease "$OUTPUT_DIR" 6 >/dev/null  # 3
    bash "$BACKOFF" decrease "$OUTPUT_DIR" 6 >/dev/null  # 2 effective
    run bash "$DISPATCH" acquire "$OUTPUT_DIR" 6 2
    [[ "$status" -eq 0 ]]
    run bash "$DISPATCH" acquire "$OUTPUT_DIR" 6 2
    [[ "$status" -eq 0 ]]
    # Two slots claimed against the throttled cap of 2 — the third must NOT succeed,
    # even though the BASE cap is 6.
    run bash "$DISPATCH" acquire "$OUTPUT_DIR" 6 1
    [[ "$status" -eq 1 ]]
    run bash "$DISPATCH" count "$OUTPUT_DIR"
    [[ "$output" == "2" ]]
}

@test "acquire ok line reports the effective (throttled) cap" {
    bash "$DISPATCH" reset "$OUTPUT_DIR" 6 >/dev/null
    bash "$BACKOFF" decrease "$OUTPUT_DIR" 6 >/dev/null  # 3
    run bash "$DISPATCH" acquire "$OUTPUT_DIR" 6 2
    [[ "$output" == "ok 1/3" ]]
}

@test "maxcap prints the BASE cap, ignoring the congestion cap" {
    bash "$DISPATCH" reset "$OUTPUT_DIR" 6 >/dev/null
    bash "$BACKOFF" decrease "$OUTPUT_DIR" 6 >/dev/null  # cap -> 3
    run bash "$DISPATCH" maxcap "$OUTPUT_DIR" 6
    [[ "$output" == "6" ]]
}

@test "unknown subcommand exits 2" {
    run bash "$BACKOFF" bogus
    [[ "$status" -eq 2 ]]
}
