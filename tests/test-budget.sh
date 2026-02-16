#!/usr/bin/env bash
# Test budget configuration and cost estimation
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PASS=0
FAIL=0

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }

echo "=== Budget Configuration Tests ==="

# Test 1: budget.yaml exists and is valid YAML
if python3 -c "import yaml; yaml.safe_load(open('${PLUGIN_DIR}/config/flux-drive/budget.yaml'))" 2>/dev/null; then
  pass "budget.yaml is valid YAML"
else
  fail "budget.yaml is not valid YAML"
fi

# Test 2: budget.yaml has required top-level keys
for key in budgets agent_defaults slicing_multiplier min_agents enforcement; do
  if grep -q "^${key}:" "${PLUGIN_DIR}/config/flux-drive/budget.yaml"; then
    pass "budget.yaml has key: ${key}"
  else
    fail "budget.yaml missing key: ${key}"
  fi
done

# Test 3: All input types have budgets
for type in plan brainstorm prd spec diff-small diff-large repo other; do
  if grep -q "  ${type}:" "${PLUGIN_DIR}/config/flux-drive/budget.yaml"; then
    pass "Budget defined for type: ${type}"
  else
    fail "Budget missing for type: ${type}"
  fi
done

# Test 4: All agent categories have defaults
for cat in review cognitive research oracle generated; do
  if grep -q "  ${cat}:" "${PLUGIN_DIR}/config/flux-drive/budget.yaml"; then
    pass "Default estimate for category: ${cat}"
  else
    fail "Default estimate missing for category: ${cat}"
  fi
done

# Test 5: estimate-costs.sh exists and is executable
if [[ -x "${PLUGIN_DIR}/scripts/estimate-costs.sh" ]]; then
  pass "estimate-costs.sh is executable"
else
  fail "estimate-costs.sh is not executable"
fi

# Test 6: estimate-costs.sh produces valid JSON
OUTPUT=$(bash "${PLUGIN_DIR}/scripts/estimate-costs.sh" 2>/dev/null || echo "SCRIPT_FAILED")
if [[ "$OUTPUT" != "SCRIPT_FAILED" ]] && echo "$OUTPUT" | jq -e '.defaults' >/dev/null 2>&1; then
  pass "estimate-costs.sh produces valid JSON with defaults"
else
  fail "estimate-costs.sh did not produce valid JSON"
fi

# Test 7: estimate-costs.sh handles --slicing flag
OUTPUT=$(bash "${PLUGIN_DIR}/scripts/estimate-costs.sh" --slicing 2>/dev/null || echo "SCRIPT_FAILED")
if [[ "$OUTPUT" != "SCRIPT_FAILED" ]] && echo "$OUTPUT" | jq -e '.slicing_multiplier' >/dev/null 2>&1; then
  MULT=$(echo "$OUTPUT" | jq -r '.slicing_multiplier')
  if [[ "$MULT" == "0.5" ]]; then
    pass "Slicing multiplier is 0.5"
  else
    fail "Slicing multiplier is $MULT (expected 0.5)"
  fi
else
  fail "estimate-costs.sh --slicing failed"
fi

# Test 8: SKILL-compact.md references Step 1.2c
if grep -q "Step 1.2c" "${PLUGIN_DIR}/skills/flux-drive/SKILL-compact.md"; then
  pass "SKILL-compact.md references Step 1.2c (budget cut)"
else
  fail "SKILL-compact.md missing Step 1.2c reference"
fi

# Test 9: SKILL-compact.md mentions Est. Tokens in triage table
if grep -q "Est. Tokens" "${PLUGIN_DIR}/skills/flux-drive/SKILL-compact.md"; then
  pass "Triage table includes Est. Tokens column"
else
  fail "Triage table missing Est. Tokens column"
fi

# Test 10: synthesize.md references cost report
if grep -q "Cost Report\|cost_report\|Step 3.4b" "${PLUGIN_DIR}/skills/flux-drive/phases/synthesize.md"; then
  pass "synthesize.md references cost report"
else
  fail "synthesize.md missing cost report reference"
fi

# Test 11: AGENTS.md contains Measurement Definitions
if grep -q "Measurement Definitions" "${PLUGIN_DIR}/AGENTS.md"; then
  pass "AGENTS.md contains Measurement Definitions"
else
  fail "AGENTS.md missing Measurement Definitions"
fi

# Test 12: min_agents >= 2
MIN=$(grep "^min_agents:" "${PLUGIN_DIR}/config/flux-drive/budget.yaml" | sed 's/.*: *//' | tr -d '[:space:]')
if [[ "$MIN" -ge 2 ]]; then
  pass "min_agents is >= 2 (value: $MIN)"
else
  fail "min_agents is < 2 (value: $MIN)"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
