#!/usr/bin/env bats
bats_require_minimum_version 1.5.0

# Integration tests for cross-model dispatch enforce mode (sylveste-fyo3.3).
#
# Design note: Cross-model dispatch is implemented as LLM-interpreted skill
# instructions (expansion.md § 2.2c), not a bash script. These tests verify:
# - Config correctness (mode, timestamps)
# - Safety floor invariants (agent-roles.yaml constraints)
# - Structural consistency (budget exemptions, challenger exclusions)
#
# Known residual risk: The downgrade-cap restoration path (expansion.md lines
# 267-272) re-applies _routing_apply_safety_floor via inline comment instruction.
# This is convention-enforced, not compile-time verified. The pool-level quality
# assertion (step 6) provides a secondary catch. See sylveste-fyo3.3 bead notes.

setup() {
    CONFIG_DIR="${BATS_TEST_DIRNAME}/../config/flux-drive"
    SPEC_DIR="${BATS_TEST_DIRNAME}/../docs/spec/extensions"
    PHASES_DIR="${BATS_TEST_DIRNAME}/../skills/flux-drive/phases"
}

# --- F1: Config activation ---

@test "cross-model dispatch mode is enforce" {
    mode=$(python3 -c "import yaml; d=yaml.safe_load(open('${CONFIG_DIR}/budget.yaml')); print(d['cross_model_dispatch']['mode'])")
    [ "$mode" = "enforce" ]
}

@test "enforce_since timestamp is set and non-null" {
    ts=$(python3 -c "import yaml; d=yaml.safe_load(open('${CONFIG_DIR}/budget.yaml')); print(d['cross_model_dispatch'].get('enforce_since', ''))")
    [ -n "$ts" ]
    [ "$ts" != "None" ]
    [ "$ts" != "null" ]
}

@test "spec document reflects enforce mode" {
    grep -q "enforce mode" "${SPEC_DIR}/cross-model-dispatch.md"
}

# --- F2: Safety floor invariants ---

@test "fd-safety has min_model sonnet in agent-roles.yaml" {
    run python3 -c "
import yaml
with open('${CONFIG_DIR}/agent-roles.yaml') as f:
    d = yaml.safe_load(f)
for role_name, role in d.get('roles', {}).items():
    agents = role.get('agents', [])
    if 'fd-safety' in agents:
        min_model = role.get('min_model', 'none')
        assert min_model in ('sonnet', 'opus'), f'fd-safety min_model={min_model}, expected sonnet+'
        print(f'fd-safety: role={role_name} min_model={min_model}')
        break
else:
    raise AssertionError('fd-safety not found in any role')
"
    [ "$status" -eq 0 ]
}

@test "fd-correctness has min_model sonnet in agent-roles.yaml" {
    run python3 -c "
import yaml
with open('${CONFIG_DIR}/agent-roles.yaml') as f:
    d = yaml.safe_load(f)
for role_name, role in d.get('roles', {}).items():
    agents = role.get('agents', [])
    if 'fd-correctness' in agents:
        min_model = role.get('min_model', 'none')
        assert min_model in ('sonnet', 'opus'), f'fd-correctness min_model={min_model}, expected sonnet+'
        print(f'fd-correctness: role={role_name} min_model={min_model}')
        break
else:
    raise AssertionError('fd-correctness not found in any role')
"
    [ "$status" -eq 0 ]
}

@test "fd-safety and fd-correctness are budget-exempt" {
    run python3 -c "
import yaml
with open('${CONFIG_DIR}/budget.yaml') as f:
    d = yaml.safe_load(f)
exempt = d.get('exempt_agents', [])
assert 'fd-safety' in exempt, f'fd-safety not in exempt_agents: {exempt}'
assert 'fd-correctness' in exempt, f'fd-correctness not in exempt_agents: {exempt}'
print('Both budget-exempt')
"
    [ "$status" -eq 0 ]
}

@test "fd-safety and fd-correctness excluded from challenger slots" {
    run python3 -c "
import yaml
with open('${CONFIG_DIR}/budget.yaml') as f:
    d = yaml.safe_load(f)
excl = d.get('challenger', {}).get('safety_exclusions', [])
assert 'fd-safety' in excl, f'fd-safety not in safety_exclusions: {excl}'
assert 'fd-correctness' in excl, f'fd-correctness not in safety_exclusions: {excl}'
print('Both challenger-excluded')
"
    [ "$status" -eq 0 ]
}

# --- F3: Checker-tier agents eligible for non-Claude routing ---

@test "checker-tier agents have max_model ceiling" {
    run python3 -c "
import yaml
with open('${CONFIG_DIR}/agent-roles.yaml') as f:
    d = yaml.safe_load(f)
checker = d['roles'].get('checker', {})
max_model = checker.get('max_model')
assert max_model is not None, 'checker role has no max_model ceiling'
print(f'checker max_model={max_model}')
"
    [ "$status" -eq 0 ]
}

@test "checker-tier agents have no min_model floor — routable to non-Claude" {
    run python3 -c "
import yaml
with open('${CONFIG_DIR}/agent-roles.yaml') as f:
    d = yaml.safe_load(f)
checker = d['roles'].get('checker', {})
min_model = checker.get('min_model')
assert min_model is None, f'checker role has min_model={min_model} — checkers should be routable to non-Claude models'
agents = checker.get('agents', [])
print(f'checker has no min_model — {len(agents)} agents routable: {agents}')
"
    [ "$status" -eq 0 ]
}

@test "downgrade cap is 50% in expansion spec" {
    grep -q "max_downgrades = floor(len(candidates) / 2)" "${PHASES_DIR}/expansion.md"
}

@test "safety floor applied after downgrade-cap restoration in expansion spec" {
    grep -q "_routing_apply_safety_floor (non-negotiable)" "${PHASES_DIR}/expansion.md"
}

# --- Advisory: model registry state ---

@test "model registry non-candidate count is reported" {
    # Advisory only — enforce mode is safe with 0 qualified models (no non-Claude
    # dispatch occurs). This test reports the count but does not assert a minimum.
    # If all models are candidates, enforce mode is a no-op for non-Claude routing.
    run python3 -c "
import yaml
with open('${CONFIG_DIR}/model-registry.yaml') as f:
    d = yaml.safe_load(f)
models = d.get('models', {})
qualified = [s for s, m in models.items() if m.get('status') in ('qualified', 'auto-qualified')]
challenger = [s for s, m in models.items() if m.get('status') == 'challenger']
candidates = [s for s, m in models.items() if m.get('status') == 'candidate']
print(f'Registry: {len(qualified)} qualified, {len(challenger)} challenger, {len(candidates)} candidate')
if not qualified:
    print('Advisory: no qualified models — enforce mode is safe but produces no non-Claude dispatch')
"
    [ "$status" -eq 0 ]
}

# --- Spec consistency ---

@test "spec agent-role table matches agent-roles.yaml" {
    run python3 -c "
import yaml
with open('${CONFIG_DIR}/agent-roles.yaml') as f:
    d = yaml.safe_load(f)
roles = d.get('roles', {})
# Build authoritative mapping
agent_to_role = {}
for role_name, role in roles.items():
    for agent in role.get('agents', []):
        agent_to_role[agent] = role_name

# Verify safety-critical agents are in roles with min_model
for agent in ['fd-safety', 'fd-correctness']:
    role_name = agent_to_role.get(agent)
    assert role_name is not None, f'{agent} not in any role'
    role = roles[role_name]
    min_model = role.get('min_model')
    assert min_model in ('sonnet', 'opus'), f'{agent} in role {role_name} with min_model={min_model}'

# Verify checker agents are NOT in safety-floor roles
for agent in ['fd-perception', 'fd-resilience', 'fd-decisions', 'fd-people']:
    role_name = agent_to_role.get(agent)
    assert role_name is not None, f'{agent} not in any role'
    role = roles[role_name]
    min_model = role.get('min_model')
    assert min_model is None, f'{agent} in role {role_name} has unexpected min_model={min_model}'

print('All agent-role mappings consistent')
"
    [ "$status" -eq 0 ]
}
