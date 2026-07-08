#!/usr/bin/env bats
# Tests for verify-synthesis-grounding.sh (issue #10, finding C-5):
# structural grounding of synthesized findings against agent Findings Indexes.

bats_require_minimum_version 1.5.0

setup() {
    SCRIPT="$BATS_TEST_DIRNAME/../scripts/verify-synthesis-grounding.sh"
    TEST_DIR="$(mktemp -d)"
    RUN="RUN-UUID-1"
}

teardown() {
    [[ -d "$TEST_DIR" ]] && rm -rf "$TEST_DIR"
}

_agent() {
    # _agent <name> <run-uuid> <index-line...>
    local name="$1" uuid="$2"; shift 2
    {
        echo "<!-- run-uuid: ${uuid} -->"
        echo "### Findings Index"
        for line in "$@"; do echo "$line"; done
        echo "Verdict: risky"
    } > "$TEST_DIR/${name}.md"
}

@test "faithful synthesis (all findings grounded) passes" {
    _agent fd-safety "$RUN" '- P0 | P0-1 | "Auth" | Token leak' '- P1 | P1-1 | "Cache" | Stale'
    echo '{"findings":[{"id":"P0-1","severity":"P0"},{"id":"P1-1","severity":"P1"}]}' > "$TEST_DIR/findings.json"
    FLUX_RUN_UUID="$RUN" run bash "$SCRIPT" "$TEST_DIR"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"OK"* ]]
}

@test "invented P0 finding (not in any index) fails with exit 3" {
    _agent fd-safety "$RUN" '- P0 | P0-1 | "Auth" | Token leak'
    echo '{"findings":[{"id":"P0-1","severity":"P0"},{"id":"P0-99","severity":"P0"}]}' > "$TEST_DIR/findings.json"
    FLUX_RUN_UUID="$RUN" run bash "$SCRIPT" "$TEST_DIR"
    [[ "$status" -eq 3 ]]
    [[ "$output" == *"P0-99"* ]]
    [[ "$output" == *"VIOLATION"* ]]
}

@test "invented P2 only warns but passes (exit 0)" {
    _agent fd-quality "$RUN" '- P2 | P2-1 | "Style" | Naming'
    echo '{"findings":[{"id":"P2-1","severity":"P2"},{"id":"P2-99","severity":"P2"}]}' > "$TEST_DIR/findings.json"
    FLUX_RUN_UUID="$RUN" run bash "$SCRIPT" "$TEST_DIR"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"warn"* ]]
}

@test "--strict fails on any ungrounded finding" {
    _agent fd-quality "$RUN" '- P2 | P2-1 | "Style" | Naming'
    echo '{"findings":[{"id":"P2-99","severity":"P2"}]}' > "$TEST_DIR/findings.json"
    FLUX_RUN_UUID="$RUN" run bash "$SCRIPT" "$TEST_DIR" --strict
    [[ "$status" -eq 3 ]]
}

@test "foreign file (wrong run-uuid) cannot ground an invented finding" {
    _agent fd-safety "$RUN" '- P0 | P0-1 | "Auth" | Token leak'
    _agent fd-stale OLD-RUN '- P0 | P0-99 | "X" | invented'
    echo '{"findings":[{"id":"P0-99","severity":"P0"}]}' > "$TEST_DIR/findings.json"
    FLUX_RUN_UUID="$RUN" run bash "$SCRIPT" "$TEST_DIR"
    [[ "$status" -eq 3 ]]
    [[ "$output" == *"P0-99"* ]]
}

@test "severity escalation (P1 in index, P0 in synth) warns by default" {
    _agent fd-safety "$RUN" '- P1 | P1-1 | "Cache" | Stale'
    echo '{"findings":[{"id":"P1-1","severity":"P0"}]}' > "$TEST_DIR/findings.json"
    FLUX_RUN_UUID="$RUN" run bash "$SCRIPT" "$TEST_DIR"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"severity differs"* ]]
}

@test "missing findings.json exits 2" {
    _agent fd-safety "$RUN" '- P0 | P0-1 | "Auth" | Token leak'
    FLUX_RUN_UUID="$RUN" run bash "$SCRIPT" "$TEST_DIR"
    [[ "$status" -eq 2 ]]
}

@test "--json emits machine-readable status" {
    _agent fd-safety "$RUN" '- P0 | P0-1 | "Auth" | Token leak'
    echo '{"findings":[{"id":"P0-1","severity":"P0"}]}' > "$TEST_DIR/findings.json"
    FLUX_RUN_UUID="$RUN" run bash "$SCRIPT" "$TEST_DIR" --json
    [[ "$status" -eq 0 ]]
    echo "$output" | jq -e '.status == "ok"' >/dev/null
    echo "$output" | jq -e '.checked == 1' >/dev/null
}
