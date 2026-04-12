#!/usr/bin/env bats
bats_require_minimum_version 1.5.0

setup() {
    SCRIPT_DIR="${BATS_TEST_DIRNAME}/../scripts"
    FIXTURES_DIR="${BATS_TEST_DIRNAME}/fixtures/qualification"
    TMPDIR_SCORE="$(mktemp -d)"
    export FLUXBENCH_RESULTS_JSONL="${TMPDIR_SCORE}/results.jsonl"
}

teardown() {
    rm -rf "$TMPDIR_SCORE"
}

# Helper: create qualification output with required qualification_run_id
_make_qual_output() {
    local model="${1:-test-model}" findings="${2:-[]}" fcr="${3:-1.0}"
    jq -n --arg m "$model" --argjson f "$findings" --arg fcr "$fcr" \
      '{model_slug:$m, findings:$f, format_compliance_rate:($fcr|tonumber),
        metadata:{agent_type:"checker",baseline_model:"claude-sonnet-4-6",
        timestamp:"2026-04-07T00:00:00Z",qualification_run_id:("qr-"+($m))}}'
}

@test "score.sh exits 0 with valid qualification output" {
    _make_qual_output "test-model" \
      '[{"severity":"P1","location":"file.py:10","description":"Missing null check","category":"correctness"}]' \
      > "${TMPDIR_SCORE}/qual-output.json"
    cat > "${TMPDIR_SCORE}/baseline.json" <<'JSON'
    {"findings":[{"severity":"P1","location":"file.py:10","description":"Missing null check","category":"correctness"},{"severity":"P2","location":"file.py:20","description":"Missing docstring","category":"style"}]}
JSON
    run bash "${SCRIPT_DIR}/fluxbench-score.sh" "${TMPDIR_SCORE}/qual-output.json" "${TMPDIR_SCORE}/baseline.json" "${TMPDIR_SCORE}/result.json"
    [ "$status" -eq 0 ]
    [ -f "${TMPDIR_SCORE}/result.json" ]
    run jq -r '.qualification_run_id' "${TMPDIR_SCORE}/result.json"
    [ "$output" = "qr-test-model" ]
}

@test "score.sh computes finding-recall correctly" {
    _make_qual_output "test-model" \
      '[{"severity":"P1","location":"file.py:10","description":"Missing null check","category":"correctness"}]' \
      > "${TMPDIR_SCORE}/qual-output.json"
    cat > "${TMPDIR_SCORE}/baseline.json" <<'JSON'
    {"findings":[{"severity":"P1","location":"file.py:10","description":"Missing null check","category":"correctness"},{"severity":"P2","location":"file.py:20","description":"Missing docstring","category":"style"}]}
JSON
    run bash "${SCRIPT_DIR}/fluxbench-score.sh" "${TMPDIR_SCORE}/qual-output.json" "${TMPDIR_SCORE}/baseline.json" "${TMPDIR_SCORE}/result.json"
    [ "$status" -eq 0 ]
    # Weighted recall: found P1 (weight 2), missed P2 (weight 1). = 2/3 = 0.667
    recall=$(jq -r '.metrics["fluxbench-finding-recall"]' "${TMPDIR_SCORE}/result.json")
    python3 -c "assert abs(float('${recall}') - 0.667) < 0.01, f'Expected ~0.667, got ${recall}'"
}

@test "score.sh auto-fails when P0 finding missed" {
    _make_qual_output "test-model" \
      '[{"severity":"P2","location":"file.py:20","description":"Style issue","category":"style"}]' \
      > "${TMPDIR_SCORE}/qual-output.json"
    cat > "${TMPDIR_SCORE}/baseline.json" <<'JSON'
    {"findings":[{"severity":"P0","location":"file.py:5","description":"SQL injection","category":"security"},{"severity":"P2","location":"file.py:20","description":"Style issue","category":"style"}]}
JSON
    run bash "${SCRIPT_DIR}/fluxbench-score.sh" "${TMPDIR_SCORE}/qual-output.json" "${TMPDIR_SCORE}/baseline.json" "${TMPDIR_SCORE}/result.json"
    [ "$status" -eq 0 ]
    p0_fail=$(jq -r '.gate_results["fluxbench-finding-recall"].p0_auto_fail' "${TMPDIR_SCORE}/result.json")
    [ "$p0_fail" = "true" ]
}

@test "score.sh handles empty baseline without division by zero" {
    _make_qual_output "test-model" '[]' > "${TMPDIR_SCORE}/qual-output.json"
    cat > "${TMPDIR_SCORE}/baseline.json" <<'JSON'
    {"findings":[]}
JSON
    run bash "${SCRIPT_DIR}/fluxbench-score.sh" "${TMPDIR_SCORE}/qual-output.json" "${TMPDIR_SCORE}/baseline.json" "${TMPDIR_SCORE}/result.json"
    [ "$status" -eq 0 ]
    recall=$(jq -r '.metrics["fluxbench-finding-recall"]' "${TMPDIR_SCORE}/result.json")
    [ "$recall" = "1" ]
}

@test "score.sh concurrent writes produce valid JSONL" {
    for i in $(seq 1 10); do
        _make_qual_output "model-${i}" '[]' > "${TMPDIR_SCORE}/qual-${i}.json"
        cp "${TMPDIR_SCORE}/qual-${i}.json" "${TMPDIR_SCORE}/baseline-${i}.json"
        bash "${SCRIPT_DIR}/fluxbench-score.sh" "${TMPDIR_SCORE}/qual-${i}.json" \
          "${TMPDIR_SCORE}/baseline-${i}.json" "${TMPDIR_SCORE}/result-${i}.json" &
    done
    wait
    # Exactly 10 lines
    lines=$(wc -l < "${FLUXBENCH_RESULTS_JSONL}")
    [ "$lines" -eq 10 ]
    # Each line must be valid JSON with correct model_slug
    while IFS= read -r line; do
        echo "$line" | jq -e '.model_slug' >/dev/null 2>&1
    done < "${FLUXBENCH_RESULTS_JSONL}"
    # All 10 model slugs present
    slugs=$(jq -r '.model_slug' "${FLUXBENCH_RESULTS_JSONL}" | sort -u | wc -l)
    [ "$slugs" -eq 10 ]
}

@test "score.sh format-compliance is binary gate" {
    _make_qual_output "test-model" '[]' '0.94' > "${TMPDIR_SCORE}/qual-output.json"
    cat > "${TMPDIR_SCORE}/baseline.json" <<'JSON'
    {"findings":[]}
JSON
    run bash "${SCRIPT_DIR}/fluxbench-score.sh" "${TMPDIR_SCORE}/qual-output.json" "${TMPDIR_SCORE}/baseline.json" "${TMPDIR_SCORE}/result.json"
    [ "$status" -eq 0 ]
    gate=$(jq -r '.gate_results["fluxbench-format-compliance"].passed' "${TMPDIR_SCORE}/result.json")
    [ "$gate" = "false" ]
}

@test "score.sh fails on invalid qualification output JSON" {
    echo "not json" > "${TMPDIR_SCORE}/bad-qual.json"
    cat > "${TMPDIR_SCORE}/baseline.json" <<'JSON'
    {"findings":[]}
JSON
    run bash "${SCRIPT_DIR}/fluxbench-score.sh" "${TMPDIR_SCORE}/bad-qual.json" "${TMPDIR_SCORE}/baseline.json" "${TMPDIR_SCORE}/result.json"
    [ "$status" -ne 0 ]
}

@test "score.sh fails when qualification_run_id is missing" {
    jq -n '{model_slug: "test", findings: [], format_compliance_rate: 1.0, metadata: {}}' > "${TMPDIR_SCORE}/no-id.json"
    cat > "${TMPDIR_SCORE}/baseline.json" <<'JSON'
    {"findings":[]}
JSON
    run bash "${SCRIPT_DIR}/fluxbench-score.sh" "${TMPDIR_SCORE}/no-id.json" "${TMPDIR_SCORE}/baseline.json" "${TMPDIR_SCORE}/result.json"
    [ "$status" -ne 0 ]
}

@test "score.sh detects P0 severity downgrade" {
    # Model finds the P0 finding but reports it as P1
    _make_qual_output "test-model" \
      '[{"severity":"P1","location":"file.py:5","description":"SQL injection vulnerability","category":"security"}]' \
      > "${TMPDIR_SCORE}/qual-output.json"
    cat > "${TMPDIR_SCORE}/baseline.json" <<'JSON'
    {"findings":[{"severity":"P0","location":"file.py:5","description":"SQL injection vulnerability","category":"security"}]}
JSON
    run bash "${SCRIPT_DIR}/fluxbench-score.sh" "${TMPDIR_SCORE}/qual-output.json" "${TMPDIR_SCORE}/baseline.json" "${TMPDIR_SCORE}/result.json"
    [ "$status" -eq 0 ]
    p0_fail=$(jq -r '.gate_results["fluxbench-finding-recall"].p0_auto_fail' "${TMPDIR_SCORE}/result.json")
    [ "$p0_fail" = "true" ]
}
