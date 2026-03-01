#!/usr/bin/env bats
# Tests for estimate-costs.sh fleet registry integration (F3)

bats_require_minimum_version 1.5.0

setup() {
    SCRIPT_DIR="$BATS_TEST_DIRNAME/../scripts"
    TEST_DIR="$(mktemp -d)"
    export PATH="$HOME/.local/bin:$PATH"
}

teardown() {
    [[ -d "$TEST_DIR" ]] && rm -rf "$TEST_DIR"
}

# Helper: create minimal interstat DB
_create_minimal_db() {
    local db="$1"
    sqlite3 "$db" "
      CREATE TABLE agent_runs (
        id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, session_id TEXT NOT NULL,
        agent_name TEXT NOT NULL, invocation_id TEXT, subagent_type TEXT,
        description TEXT, wall_clock_ms INTEGER, result_length INTEGER,
        input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
        cache_creation_tokens INTEGER, total_tokens INTEGER, model TEXT,
        parsed_at TEXT, bead_id TEXT DEFAULT '', phase TEXT DEFAULT ''
      );
    "
}

@test "estimate-costs outputs valid JSON with defaults when no DB" {
    HOME="$TEST_DIR" run bash "$SCRIPT_DIR/estimate-costs.sh" --model claude-sonnet-4-6
    [[ "$status" -eq 0 ]]
    echo "$output" | jq -e '.defaults.review' >/dev/null
    echo "$output" | jq -e '.slicing_multiplier' >/dev/null
}

@test "estimate-costs uses interstat data for agents with >= 3 runs" {
    local db="$TEST_DIR/metrics.db"
    _create_minimal_db "$db"
    # Insert 4 runs for fd-safety
    for i in 1 2 3 4; do
        sqlite3 "$db" "INSERT INTO agent_runs (timestamp, session_id, agent_name, input_tokens, output_tokens, total_tokens, model)
          VALUES ('2026-02-0${i}T10:00:00Z', 's${i}', 'fd-safety', 15000, 20000, 35000, 'claude-sonnet-4-6');"
    done

    HOME="$TEST_DIR" run bash -c "DB_PATH='$db' source '$SCRIPT_DIR/estimate-costs.sh' --model claude-sonnet-4-6 2>/dev/null"
    # Run directly instead — estimate-costs.sh uses hardcoded DB_PATH
    # Override by symlinking
    mkdir -p "$TEST_DIR/.claude/interstat"
    cp "$db" "$TEST_DIR/.claude/interstat/metrics.db"

    HOME="$TEST_DIR" run bash "$SCRIPT_DIR/estimate-costs.sh" --model claude-sonnet-4-6
    [[ "$status" -eq 0 ]]
    local source
    source="$(echo "$output" | jq -r '.estimates["fd-safety"].source // "none"')"
    [[ "$source" == "interstat" ]]
}

@test "estimate-costs falls back to fleet registry for agents with < 3 runs" {
    # Create interstat DB with only 1 run for fd-safety
    local db="$TEST_DIR/metrics.db"
    _create_minimal_db "$db"
    sqlite3 "$db" "INSERT INTO agent_runs (timestamp, session_id, agent_name, input_tokens, output_tokens, total_tokens, model)
      VALUES ('2026-03-01T10:00:00Z', 's1', 'fd-safety', 15000, 20000, 35000, 'claude-sonnet-4-6');"
    mkdir -p "$TEST_DIR/.claude/interstat"
    cp "$db" "$TEST_DIR/.claude/interstat/metrics.db"

    # Create fleet registry with actual_tokens for fd-safety
    local registry="$TEST_DIR/fleet-registry.yaml"
    cat > "$registry" << 'YAML'
version: "1.0"
last_enrichment: "2026-02-15T00:00:00Z"
capability_vocabulary: []
agents:
  fd-safety:
    source: interflux
    category: review
    description: "Safety reviewer"
    capabilities: []
    roles: [fd-safety]
    runtime:
      mode: subagent
      subagent_type: "interflux:review:fd-safety"
    models:
      preferred: sonnet
      supported: [sonnet, opus]
      actual_tokens:
        claude-sonnet-4-6: {mean: 35000, p50: 33000, p90: 45000, runs: 8}
    cold_start_tokens: 800
    tags: [technical]
YAML

    CLAVAIN_FLEET_REGISTRY="$registry" HOME="$TEST_DIR" run bash "$SCRIPT_DIR/estimate-costs.sh" --model claude-sonnet-4-6
    [[ "$status" -eq 0 ]]
    local source
    source="$(echo "$output" | jq -r '.estimates["fd-safety"].source // "none"')"
    [[ "$source" == "fleet-registry" ]]
    local est
    est="$(echo "$output" | jq -r '.estimates["fd-safety"].est_tokens')"
    [[ "$est" -gt 0 ]]
}
