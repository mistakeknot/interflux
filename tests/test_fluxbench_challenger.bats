#!/usr/bin/env bats
bats_require_minimum_version 1.5.0

setup() {
    SCRIPT_DIR="${BATS_TEST_DIRNAME}/../scripts"
    TMPDIR_CHAL="$(mktemp -d)"
    export MODEL_REGISTRY="${TMPDIR_CHAL}/model-registry.yaml"
    export BUDGET_CONFIG="${TMPDIR_CHAL}/budget.yaml"
    export FLUXBENCH_RESULTS_JSONL="${TMPDIR_CHAL}/results.jsonl"

    # Create minimal budget config
    cat > "$BUDGET_CONFIG" <<'YAML'
challenger:
  enabled: true
  slots: 1
  pre_inclusion_runs: 2
  promotion_threshold: 5
  early_exit_margin: 0.20
  stale_threshold: 10
  safety_exclusions:
    - fd-safety
    - fd-correctness
YAML

    # Create minimal registry with one qualifying model
    cat > "$MODEL_REGISTRY" <<'YAML'
fluxbench:
  challenger_slots: 1
models:
  test-model-a:
    status: qualifying
    qualified_via: real
    provider: openrouter
    fluxbench:
      format_compliance: 0.98
      finding_recall: 0.75
      false_positive_rate: 0.10
      severity_accuracy: 0.80
      persona_adherence: null
YAML
}

teardown() {
    rm -rf "$TMPDIR_CHAL"
}

@test "challenger select exits 0 with qualifying candidate" {
    # Need enough JSONL entries to satisfy pre_inclusion_runs (2) — compact single-line
    for i in 1 2 3; do
        jq -cn --arg slug "test-model-a" \
          '{model_slug: $slug, gate_results: {}}' >> "$FLUXBENCH_RESULTS_JSONL"
    done
    run --separate-stderr bash "${SCRIPT_DIR}/fluxbench-challenger.sh" select
    [ "$status" -eq 0 ]
    echo "$output" | jq -e '.selected == "test-model-a"'
}

@test "challenger select returns null when no candidates" {
    # Remove models
    cat > "$MODEL_REGISTRY" <<'YAML'
models: {}
YAML
    run bash "${SCRIPT_DIR}/fluxbench-challenger.sh" select
    [ "$status" -eq 0 ]
    echo "$output" | jq -e '.selected == null'
}

@test "challenger select filters out mock-qualified models" {
    cat > "$MODEL_REGISTRY" <<'YAML'
models:
  mock-model:
    status: auto-qualified
    qualified_via: mock
    fluxbench:
      format_compliance: 1.0
      finding_recall: 1.0
      false_positive_rate: 0.0
      severity_accuracy: 1.0
YAML
    run bash "${SCRIPT_DIR}/fluxbench-challenger.sh" select
    [ "$status" -eq 0 ]
    echo "$output" | jq -e '.selected == null'
}

@test "challenger evaluate returns insufficient_runs when below threshold" {
    run bash "${SCRIPT_DIR}/fluxbench-challenger.sh" evaluate test-model-a
    [ "$status" -eq 0 ]
    echo "$output" | jq -e '.verdict == "insufficient_runs"'
}

@test "challenger status shows null when no challenger active" {
    run bash "${SCRIPT_DIR}/fluxbench-challenger.sh" status
    [ "$status" -eq 0 ]
    echo "$output" | jq -e '.challenger == null'
}

@test "challenger status shows active challenger" {
    cat > "$MODEL_REGISTRY" <<'YAML'
models:
  test-model-a:
    status: challenger
    qualified_via: real
    fluxbench:
      format_compliance: 0.98
YAML
    run bash "${SCRIPT_DIR}/fluxbench-challenger.sh" status
    [ "$status" -eq 0 ]
    echo "$output" | jq -e '.challenger == "test-model-a"'
}

@test "challenger evaluate rejects stale model" {
    # Create enough JSONL entries to exceed stale_threshold (10) — must be compact single-line JSON
    for i in $(seq 1 11); do
        jq -cn --arg slug "test-model-a" \
          '{model_slug: $slug, gate_results: {
            "fluxbench-format-compliance": {passed: false, value: 0.5, threshold: 0.95},
            "fluxbench-finding-recall": {passed: false, value: 0.3, threshold: 0.60}
          }}' >> "$FLUXBENCH_RESULTS_JSONL"
    done

    run bash "${SCRIPT_DIR}/fluxbench-challenger.sh" evaluate test-model-a
    [ "$status" -eq 0 ]
    # Extract JSON from output (stderr may prepend status messages)
    echo "$output" | grep -E '^\{' | jq -se '.[0].verdict == "rejected"'
}

@test "challenger unknown action exits 1" {
    run bash "${SCRIPT_DIR}/fluxbench-challenger.sh" bogus
    [ "$status" -eq 1 ]
}

@test "challenger registry write is atomic — file not corrupted on success" {
    # Select to trigger a registry write
    # Need pre_inclusion_runs worth of JSONL entries
    for i in $(seq 1 3); do
        jq -cn --arg slug "test-model-a" \
          '{model_slug: $slug, gate_results: {}}' >> "$FLUXBENCH_RESULTS_JSONL"
    done

    run bash "${SCRIPT_DIR}/fluxbench-challenger.sh" select
    [ "$status" -eq 0 ]

    # Validate registry is still valid YAML
    python3 -c "import yaml; yaml.safe_load(open('${MODEL_REGISTRY}'))"
}
