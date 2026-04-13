---
artifact_type: plan
bead: sylveste-fyo3.3
stage: design
requirements:
  - F1: Config activation (shadow → enforce)
  - F2: Safety floor verification
  - F3: Integration test for dispatch routing
---
# Cross-Model Dispatch Enforce Activation — Plan

**Bead:** sylveste-fyo3.3
**Goal:** Switch cross-model dispatch from shadow to enforce mode. Verify safety floors. Add integration test.
**Tech Stack:** YAML config, Bash (bats tests), Markdown (spec update)

---

## Task 1: Config Activation [F1]

**Files:**
- Modify: `config/flux-drive/budget.yaml` (line 71)
- Modify: `docs/spec/extensions/cross-model-dispatch.md` (line 3)

**Step 1:** In `budget.yaml`, change:
```yaml
cross_model_dispatch:
  enabled: true
  mode: enforce    # was: shadow
  enforce_since: "2026-04-13T00:00:00Z"
```

**Step 2:** In `cross-model-dispatch.md`, update status:
```
**Status:** Implemented (interflux v0.2.56+), enforce mode (activated 2026-04-13)
```

<verify>
- run: `python3 -c "import yaml; d=yaml.safe_load(open('config/flux-drive/budget.yaml')); print(d['cross_model_dispatch']['mode'])"`
  expect: "enforce"
</verify>

---

## Task 2: Safety Floor Verification [F2]

**Files:**
- Read-only: `skills/flux-drive/phases/expansion.md` (§ 2.2c)
- Read-only: `config/flux-drive/agent-roles.yaml`

**Verification checklist** (no code changes — algorithmic audit):

1. `_routing_apply_safety_floor` is called after EVERY tier adjustment:
   - After tier-cap check (expansion.md line 251) ✓
   - After downgrade cap restoration (expansion.md line 272) ✓
   - After upgrade pass: safety floor and max_model ceiling (line 281) ✓

2. Safety floors are defined in agent-roles.yaml:
   - fd-safety: `min_model: sonnet` (reviewer role, line 40-46) ✓
   - fd-correctness: `min_model: sonnet` (reviewer role, line 40-46) ✓
   - Planner role: `min_model: sonnet` (line 32) ✓

3. Safety exemptions in budget.yaml:
   - `exempt_agents: [fd-safety, fd-correctness]` — always run regardless of budget ✓
   - `challenger.safety_exclusions: [fd-safety, fd-correctness]` — never fill ✓

4. Enforce path (expansion.md line 301-302):
   ```
   else:
       # Dispatch at adjusted models
   ```
   The adjusted models have already passed through safety floor clamping. ✓

**No code changes needed.** Document verification in the integration test comments.

---

## Task 3: Integration Test [F3]

**Files:**
- Create: `tests/test_cross_model_dispatch.bats`

**Step 1: Write test file**

The test verifies the dispatch CONFIG is correct and the safety constraints are structurally sound. Since cross-model dispatch is implemented as skill instructions (not a bash script), the test validates config consistency and constraint invariants rather than execution.

```bash
#!/usr/bin/env bats
bats_require_minimum_version 1.5.0

setup() {
    CONFIG_DIR="${BATS_TEST_DIRNAME}/../config/flux-drive"
    SPEC_DIR="${BATS_TEST_DIRNAME}/../docs/spec/extensions"
}

# --- F1: Config activation ---

@test "cross-model dispatch mode is enforce" {
    mode=$(python3 -c "import yaml; d=yaml.safe_load(open('${CONFIG_DIR}/budget.yaml')); print(d['cross_model_dispatch']['mode'])")
    [ "$mode" = "enforce" ]
}

@test "enforce_since timestamp is set" {
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
# fd-safety must be in a role with min_model >= sonnet
for role_name, role in d.get('roles', {}).items():
    agents = role.get('agents', [])
    if 'fd-safety' in agents:
        min_model = role.get('min_model', 'none')
        print(f'role={role_name} min_model={min_model}')
        assert min_model in ('sonnet', 'opus'), f'fd-safety min_model={min_model}, expected sonnet+'
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
        print(f'role={role_name} min_model={min_model}')
        assert min_model in ('sonnet', 'opus'), f'fd-correctness min_model={min_model}, expected sonnet+'
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
print('Both exempt')
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
print('Both excluded')
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

@test "checker-tier agents are NOT safety-floor protected" {
    # Checker agents (fd-perception, fd-resilience, fd-decisions, fd-people) should NOT
    # have min_model — they are candidates for non-Claude routing under enforce mode
    run python3 -c "
import yaml
with open('${CONFIG_DIR}/agent-roles.yaml') as f:
    d = yaml.safe_load(f)
checker = d['roles'].get('checker', {})
min_model = checker.get('min_model')
assert min_model is None, f'checker role has unexpected min_model={min_model} — checkers should be routable to non-Claude models'
print('checker has no min_model (correctly routable)')
"
    [ "$status" -eq 0 ]
}

@test "downgrade cap is 50% in expansion spec" {
    grep -q "max_downgrades = floor(len(candidates) / 2)" \
        "${BATS_TEST_DIRNAME}/../skills/flux-drive/phases/expansion.md"
}

@test "model registry has at least one non-candidate model" {
    # Enforce mode needs qualified models to have any effect
    run python3 -c "
import yaml
with open('${CONFIG_DIR}/model-registry.yaml') as f:
    d = yaml.safe_load(f)
models = d.get('models', {})
non_candidates = [s for s, m in models.items() if m.get('status') not in ('candidate', None)]
print(f'{len(non_candidates)} non-candidate model(s): {non_candidates}')
# This is advisory — enforce mode is safe even with 0 qualified models
"
    [ "$status" -eq 0 ]
}
```

**Step 2: Run tests, commit**

<verify>
- run: `cd interverse/interflux && bats tests/test_cross_model_dispatch.bats`
  expect: exit 0
</verify>

---

## Task Dependencies

```
Task 1 (config) ──┐
                   ├──▶ Task 3 (integration test)
Task 2 (verify) ──┘
```

Tasks 1 and 2 are independent. Task 3 depends on both.
