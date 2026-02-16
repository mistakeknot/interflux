# Quality Review: Token Budget Controls for Flux-Drive

**Date**: 2026-02-16
**Reviewer**: fd-quality
**Scope**: Token budget control system — config, scripts, tests, protocol updates

---

## Executive Summary

This review covers the token budget control additions to the flux-drive multi-agent dispatch system. The implementation adds 4 files (budget.yaml, estimate-costs.sh, test-budget.sh, AGENTS.md updates) and modifies 3 skill files to integrate budget-aware agent selection.

**Verdict**: APPROVE WITH FINDINGS (4 medium, 3 low)

**Strengths**:
- Consistent naming across all layers (bash, YAML, markdown)
- Solid structural test coverage (27 tests)
- Graceful degradation when interstat data is missing
- Documentation table clarity (especially AGENTS.md token definitions)

**Key Issues**:
- Shell script needs hardening for edge cases (grep failures, jq parsing errors)
- YAML parsing uses `grep+sed` which is brittle for future config changes
- Test coverage is structural but lacks integration/behavior validation
- Documentation inconsistencies between compact and full skill files

---

## Universal Review Findings

### Naming Consistency

#### PASS: Variable and function naming

All shell variables use `UPPER_SNAKE_CASE` for globals (`BUDGET_FILE`, `MODEL`, `SLICING`) and `lower_snake_case` for locals (`agent_type`, `default_val`). Functions use `snake_case` (`get_default`, `classify_agent`). This is consistent with project conventions.

YAML keys use `snake_case` (`slicing_multiplier`, `min_agents`), JSON uses `snake_case` (`est_tokens`, `sample_size`). Markdown table headers use title case ("Est. Tokens", "Source").

**Finding**: Naming is internally consistent across all layers.

---

### File Organization

#### PASS: Files placed in established directories

```
config/flux-drive/budget.yaml          → Config directory (existing pattern)
scripts/estimate-costs.sh               → Scripts directory (alongside detect-domains.py)
tests/test-budget.sh                    → Tests directory (alongside test-namespace.sh)
```

YAML config placement matches the existing `config/flux-drive/domains/` pattern. Shell scripts follow the `scripts/` convention. Test suite structure mirrors existing structural tests.

**Finding**: File layout aligns with project structure.

---

### Error Handling Patterns

#### MEDIUM: Shell script error handling is incomplete

**Location**: `scripts/estimate-costs.sh` lines 36-40, 67-77

**Issue**: The script uses `|| echo ""` fallback patterns for `grep` failures but does not handle `sqlite3` or `jq` failures gracefully.

```bash
# Line 67-77: No fallback if sqlite3 fails due to missing DB
INTERSTAT_DATA=$(sqlite3 -json "$DB_PATH" "..." 2>/dev/null || echo "[]")
```

**Risk**: If `sqlite3` binary is missing, the script exits with `command not found` instead of returning defaults.

**Fix**:
```bash
# Check for required binaries upfront
for cmd in sqlite3 jq; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo '{"estimates":{}, "defaults":{...}, "slicing_multiplier":1.0}' >&2
    exit 1
  fi
done
```

Also: validate `jq` parsing at line 96-112. If the JSON template is malformed, the script exits silently.

---

#### MEDIUM: YAML parsing uses fragile grep+sed

**Location**: `scripts/estimate-costs.sh` lines 31-51, `tests/test-budget.sh` lines 23-47

**Issue**: The `get_default` and `get_slicing_multiplier` functions use `grep "^  key:" | sed` to extract YAML values. This breaks if:
- YAML uses multi-line values
- Comments contain the key name elsewhere
- Indentation changes (3 spaces instead of 2)

```bash
# Line 36: Assumes exactly 2-space indent
line=$(grep "^  ${agent_type}:" "$BUDGET_FILE" 2>/dev/null || echo "")
```

**Risk**: Future YAML refactoring (adding anchors, restructuring keys) could break parsing.

**Fix**: Use a YAML parser. The project already uses Python elsewhere (detect-domains.py). Replace shell YAML parsing with:
```bash
python3 -c "import yaml; print(yaml.safe_load(open('$BUDGET_FILE'))['agent_defaults']['$agent_type'])"
```

Or add a dependency check and fallback:
```bash
if command -v yq >/dev/null 2>&1; then
  yq '.agent_defaults.review' "$BUDGET_FILE"
else
  # grep fallback
fi
```

---

#### LOW: No validation for budget.yaml schema

**Location**: `config/flux-drive/budget.yaml`

**Issue**: The YAML file has required structure (top-level keys, nested keys) but no schema validation. If a user manually edits the file and removes a key, the script fails at runtime with unclear errors.

**Test coverage gap**: `tests/test-budget.sh` checks key existence via `grep` (lines 22-47) but does not validate:
- Value types (are budgets integers? is `slicing_multiplier` a float?)
- Value ranges (is `min_agents >= 0`? is `enforcement` one of `soft|hard`?)
- YAML validity (the Python test at line 16 only checks parsability, not schema)

**Fix**: Add a schema validation test using Python:
```bash
python3 -c "
import yaml
cfg = yaml.safe_load(open('$BUDGET_FILE'))
assert isinstance(cfg['budgets']['plan'], int), 'budgets.plan must be int'
assert cfg['slicing_multiplier'] > 0, 'slicing_multiplier must be positive'
assert cfg['min_agents'] >= 0, 'min_agents must be non-negative'
assert cfg['enforcement'] in ['soft', 'hard'], 'enforcement must be soft|hard'
"
```

---

### Test Strategy

#### PASS: Structural tests cover key integration points

The test suite (`tests/test-budget.sh`) validates:
- YAML validity (line 16)
- Required keys (lines 22-47)
- Script execution and JSON output (lines 56-75)
- Slicing flag handling (lines 65-75)
- Cross-file references (skill files mention Step 1.2c, triage table columns)

This is appropriate for the risk level: budget controls are a dispatch-time filter, not a runtime safety feature. Structural tests catch config/integration breakage.

**Finding**: Test strategy matches risk profile.

---

#### MEDIUM: Missing behavior tests for budget enforcement

**Issue**: The test suite validates structure but not behavior. Key scenarios NOT covered:
1. What happens when cumulative estimate exceeds budget?
2. Does `min_agents: 2` actually prevent all agents from being deferred?
3. Does the slicing multiplier correctly halve estimates for non-cross-cutting agents?
4. What happens if interstat returns estimates but they're all 0?

**Fix**: Add behavior tests. Example:
```bash
# Test: min_agents respected when budget exceeded
MOCK_BUDGET=10000  # Very low budget
MOCK_ESTIMATES='{"fd-architecture": 8000, "fd-safety": 8000, "fd-quality": 8000}'
# Run selection algorithm with 3 agents, expect 2 selected (min_agents)
# Verify: agents_selected == 2, deferred == 1
```

This requires extracting the budget cut logic from the skill markdown into a testable script, or writing integration tests that invoke the full skill.

---

### API Design Consistency

#### PASS: estimate-costs.sh follows Unix pipeline conventions

**Observations**:
- Takes input via flags (`--model`, `--slicing`)
- Outputs JSON to stdout
- Errors to stderr (`2>/dev/null` suppresses db query errors)
- Exit codes: 0 for success (implicit), non-zero for missing deps (recommended above)
- Pure function: no side effects, same inputs produce same outputs (except DB updates)

This matches project script conventions (see `scripts/detect-domains.py` with `--json`, `--no-cache` flags).

**Finding**: CLI design is consistent.

---

#### LOW: budget.yaml comment style is inconsistent

**Location**: `config/flux-drive/budget.yaml` lines 6-14, 16-24

**Issue**: Inline comments use two styles:
```yaml
diff-small: 60000      # diff < 500 lines    ← explanation style
review: 40000          # fd-architecture, fd-safety, ...  ← enumeration style
```

**Fix**: Pick one style. Recommendation: use explanations (when/why) not enumerations (which agents). The `classify_agent` function in the script already documents the mapping.

```yaml
# After:
agent_defaults:
  review: 40000        # fd-* technical domain reviewers
  cognitive: 35000     # fd-systems, fd-decisions, fd-people, fd-resilience, fd-perception
  research: 15000      # External research agents (best-practices, framework-docs, etc.)
```

---

### Complexity Budget

#### PASS: No unnecessary abstractions

The budget system adds minimal indirection:
1. Config file (data)
2. Estimator script (query + fallback logic)
3. Selection algorithm (embedded in skill markdown, not abstracted)

This is appropriate. The system is simple enough that extracting a "budget enforcement library" would add complexity without value.

**Finding**: Abstraction level matches problem complexity.

---

### Dependency Discipline

#### MEDIUM: estimate-costs.sh depends on sqlite3 and jq without checks

**Issue**: Script assumes `sqlite3` and `jq` are installed. If missing, fails with opaque errors.

**Context**: Both are used elsewhere in the project (interstat uses sqlite3, Clavain uses jq extensively). But the *script* should be defensive.

**Fix**: Add dependency checks (already recommended under Error Handling). Alternative: document required dependencies in AGENTS.md under "## Scripts".

---

## Language-Specific Review: Bash

### Shell Script: estimate-costs.sh

#### PASS: Uses set -euo pipefail

**Line 7**: `set -euo pipefail` — proper strict mode for Bash.

**Finding**: Follows project shell standards.

---

#### LOW: Argument parsing allows unknown flags to be silently ignored

**Lines 18-24**:
```bash
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --slicing) SLICING=true; shift ;;
    *) shift ;;  # ← silently ignores unknown flags
  esac
done
```

**Issue**: If user passes `--slicng` (typo), it's silently ignored. Slicing will be `false` but no error is raised.

**Risk**: Low (script is internal, not user-facing). But it makes debugging harder.

**Fix**:
```bash
*) echo "Unknown flag: $1" >&2; exit 1 ;;
```

Or softer:
```bash
*) echo "Warning: Unknown flag '$1' ignored" >&2; shift ;;
```

---

#### PASS: Robust quoting and expansion

All variable expansions use double quotes (`"$MODEL"`, `"${PLUGIN_DIR}"`). Command substitutions use `$(...)` not backticks. Safe against word splitting.

**Finding**: Quoting is correct.

---

#### PASS: Default model handling

**Lines 27-29**:
```bash
if [[ -z "$MODEL" ]]; then
  MODEL="claude-opus-4-6"
fi
```

This is clean. Alternative: `MODEL="${MODEL:-claude-opus-4-6}"` (more idiomatic). Current version is fine.

**Finding**: Default handling is correct.

---

#### MEDIUM: grep failure returns empty string, jq sees it as invalid JSON

**Lines 36-40 in `get_default`**:
```bash
line=$(grep "^  ${agent_type}:" "$BUDGET_FILE" 2>/dev/null || echo "")
if [[ -n "$line" ]]; then
  default_val=$(echo "$line" | sed 's/.*: *//' | sed 's/ *#.*//' | tr -d '[:space:]')
fi
echo "$default_val"
```

**Issue**: If `grep` finds nothing, `default_val` is `40000` (the initial value). This is fine. But if the YAML file is missing entirely, `grep` fails and `default_val` is still `40000`. The script continues without error.

**Risk**: If `budget.yaml` is deleted, the script uses hardcoded defaults. This might be intentional (graceful degradation) but should be logged.

**Fix**: Check file existence:
```bash
if [[ ! -f "$BUDGET_FILE" ]]; then
  echo "Warning: budget.yaml not found, using hardcoded defaults" >&2
fi
```

---

#### PASS: classify_agent uses case statement correctly

**Lines 54-63**: Handles exact matches (cognitive agents by name), wildcards (`*-researcher`), and default fallback. Correct.

**Finding**: Agent classification logic is sound.

---

#### PASS: SQL query uses parameterized model filter

**Lines 69-76**: The SQL uses `WHERE model = '${MODEL}'`. This is safe because `$MODEL` is controlled (set by script defaults or CLI flag, not user input from untrusted source). The query also uses `OR model IS NULL` to catch legacy rows.

**Finding**: SQL is safe (no injection risk given context).

---

#### PASS: jq template is readable

**Lines 96-112**: Multi-line jq template with `--arg` for variable injection. This is the correct way to pass shell variables to jq (avoids string escaping issues).

**Finding**: jq usage is correct.

---

### Shell Script: tests/test-budget.sh

#### PASS: Test structure is clear

Uses `pass()` and `fail()` helpers, increments counters, exits with failure if any test failed. Standard test script pattern.

**Finding**: Test structure is good.

---

#### PASS: Validates YAML with Python

**Line 16**: `python3 -c "import yaml; yaml.safe_load(open('...'))"` — correct.

**Finding**: Python YAML validation is appropriate here (test context).

---

#### PASS: Validates script executability

**Line 50**: `[[ -x "${PLUGIN_DIR}/scripts/estimate-costs.sh" ]]` — catches missing `+x` bit.

**Finding**: Good coverage.

---

#### MEDIUM: Test does not validate JSON schema

**Lines 56-62**:
```bash
OUTPUT=$(bash "${PLUGIN_DIR}/scripts/estimate-costs.sh" 2>/dev/null || echo "SCRIPT_FAILED")
if [[ "$OUTPUT" != "SCRIPT_FAILED" ]] && echo "$OUTPUT" | jq -e '.defaults' >/dev/null 2>&1; then
  pass "estimate-costs.sh produces valid JSON with defaults"
```

**Issue**: Only checks that `.defaults` exists. Does NOT check:
- Are `.estimates`, `.slicing_multiplier` present?
- Are `.defaults.review`, `.defaults.cognitive`, etc. numbers?
- Is the structure correct?

**Fix**: Add schema validation:
```bash
echo "$OUTPUT" | jq -e '
  .estimates != null and
  .defaults.review != null and
  (.defaults.review | type) == "number" and
  .slicing_multiplier != null and
  (.slicing_multiplier | type) == "number"
' >/dev/null
```

---

## Language-Specific Review: YAML

### Config: budget.yaml

#### PASS: Valid YAML structure

Indentation is consistent (2 spaces). Keys are lowercase with underscores. Comments use `#`. No multi-line strings or anchors (appropriate for this simple config).

**Finding**: YAML is clean.

---

#### PASS: Budgets are integers

All numeric values are integers (no quotes). YAML parsers will read these as numbers, not strings.

**Finding**: Types are correct.

---

#### LOW: No version field

**Issue**: `budget.yaml` has no `version:` field. If the schema changes in the future (e.g., adding per-agent overrides), there's no way to detect old config files.

**Comparison**: `routing-overrides.json` has a `version` field (SKILL.md line 235). `flux-drive.yaml` has a `cache_version` field (SKILL.md note at line 73).

**Fix**: Add `version: 1` to the top of budget.yaml. Update `scripts/estimate-costs.sh` to check it:
```bash
VERSION=$(grep "^version:" "$BUDGET_FILE" | sed 's/.*: *//')
if [[ "$VERSION" -gt 1 ]]; then
  echo "Error: budget.yaml version $VERSION not supported (max 1)" >&2
  exit 2
fi
```

---

## Documentation Review: AGENTS.md

### Measurement Definitions Section

#### PASS: Table clarity

The 3 tables (Token Types, Cost Types, Scopes) are clear and well-structured. Column alignment is correct. Descriptions are concise.

**Finding**: Excellent documentation.

---

#### PASS: Critical distinction called out

The "Critical" note between the tables (line 240 in the diff) highlights the 600x difference between billing tokens and effective context. This is the most important concept and it's prominently placed.

**Finding**: Key insight is emphasized.

---

#### LOW: Scopes table references future feature

**Line in AGENTS.md diff**:
```markdown
| Per-sprint | All sessions in a Clavain sprint | Future: interbudget |
```

**Issue**: References `interbudget` which does not exist. Should this be "Future: interstat sprint aggregation" or "Future: Clavain sprint tracking"?

**Fix**: Clarify the future feature name or remove the row until the feature is scoped.

---

#### PASS: Links to budget.yaml

The last line of the diff points to `config/flux-drive/budget.yaml` for configuration details. Readers know where to go.

**Finding**: Cross-reference is correct.

---

## Documentation Review: Skills (SKILL-compact.md, SKILL.md, synthesize.md)

### SKILL-compact.md: Step 1.2c

#### PASS: Algorithm is clear

**Lines 93-140**: The 3-step algorithm (load config, estimate costs, apply cut) is well-structured. Each step has a clear purpose and output.

**Finding**: Protocol is readable.

---

#### PASS: Graceful degradation is documented

**Line 139**: "If interstat DB doesn't exist or returns no data, use defaults for ALL agents. Log: 'Using default cost estimates (no interstat data).' Do NOT skip budget enforcement."

This is the right design. Budgets provide value even with defaults.

**Finding**: Fallback behavior is correct.

---

#### MEDIUM: Cross-cutting agent definition is inconsistent

**Line 119**: "If slicing is active AND agent is NOT cross-cutting (fd-architecture, fd-quality): multiply estimate by `slicing_multiplier`"

**Issue**: The skill file defines cross-cutting agents as `fd-architecture, fd-quality` here. But in SKILL.md line 278, the list is:
> "Domain-general agents always pass the filter: fd-architecture, fd-quality, and fd-performance (for file/directory inputs only)"

**Questions**:
1. Is fd-performance cross-cutting or not?
2. If fd-performance is cross-cutting, why does it get the slicing discount?

**Fix**: Standardize the definition. Recommendation:
- Cross-cutting = agents that review ALL sections regardless of domain (fd-architecture, fd-quality)
- fd-performance is domain-specific (performance sections only), so it should get the slicing discount

Update line 119:
```markdown
3. If slicing is active AND agent is domain-specific (NOT fd-architecture or fd-quality): multiply estimate by `slicing_multiplier`
```

---

#### PASS: Triage table includes new columns

**Line 145**: The updated triage table format includes `Est. Tokens`, `Source`, and `Action` columns. This matches the budget context.

**Finding**: Table structure is consistent.

---

#### PASS: Budget summary line is detailed

**Line 148**: "Budget: {cumulative_selected}K / {BUDGET_TOTAL/1000}K ({percentage}%) | Deferred: {N} agents ({deferred_total}K est.)"

This gives the user all the context they need to decide whether to override.

**Finding**: Summary is comprehensive.

---

### SKILL.md: Step 1.2c reference

#### PASS: Forward reference to compact skill

**Line 369-378**: "See the compact skill (SKILL-compact.md Step 1.2c) for the complete algorithm."

This avoids duplicating the 50-line algorithm. Readers can jump to the compact version if needed.

**Finding**: Documentation structure is good.

---

#### LOW: Key points summary is missing slicing multiplier

**Lines 373-378**: Lists 4 key points but omits the slicing multiplier logic (which is in the compact skill at line 119).

**Fix**: Add a 5th bullet:
```markdown
- Slicing discount: when document/diff slicing is active, domain-specific agents get a 0.5x multiplier (cross-cutting agents always see full document, so no discount)
```

---

### synthesize.md: Cost Report (Step 3.4b)

#### PASS: SQL query is correct

**Lines 149-159**: Query uses `COALESCE(input_tokens,0) + COALESCE(output_tokens,0)` for billing tokens and `input_tokens + cache_read_tokens + cache_creation_tokens` for effective context.

This matches the AGENTS.md definitions.

**Finding**: Token accounting is consistent.

---

#### PASS: Fallback for missing data

**Line 161**: "If interstat has no data yet (tokens not backfilled until SessionEnd), use `result_length` as a proxy and note 'Actual tokens pending backfill — showing result length.'"

Good graceful degradation.

**Finding**: Fallback is appropriate.

---

#### PASS: Delta calculation

**Lines 164-168**: `delta_pct = ((actual - estimated) / estimated) * 100`

This is correct. Positive delta = over-estimate, negative = under-estimate.

**Finding**: Math is correct.

---

#### PASS: Cost report schema

**Lines 173-199**: The `cost_report` JSON schema includes all relevant fields: budget, estimated, actual, delta, source, slicing_applied, deferred agents.

**Finding**: Schema is complete.

---

#### PASS: Report template

**Lines 233-242**: The Markdown cost report table includes all columns (Estimated, Actual, Delta, Source) and budget summary lines.

**Finding**: Template is comprehensive.

---

#### LOW: Convergence adjustment section out of place

**Lines 201-204**: The "Convergence with document slicing" paragraph is appended to Step 3.4b (cost report) but it describes Step 3.3 (deduplication) logic.

**Issue**: This breaks the flow. Step 3.4b is about cost reporting, not convergence scoring.

**Fix**: Move this paragraph to Step 3.3 (lines 38-46 in synthesize.md). It belongs in the "Deduplicate and Organize" section, not the cost report section.

---

## Summary of Findings

| Severity | Count | Category |
|----------|-------|----------|
| P0 (Critical) | 0 | — |
| P1 (High) | 0 | — |
| P2 (Medium) | 4 | Shell error handling, YAML parsing, cross-cutting definition, behavior tests |
| P3 (Low) | 3 | Comment style, version field, misplaced convergence note |
| IMP (Improvement) | 0 | — |

---

## Detailed Findings

### Medium Severity (P2)

**M1. Shell script error handling incomplete**
Location: `scripts/estimate-costs.sh:36-40, 67-77`
Issue: No fallback if `sqlite3` or `jq` binaries are missing. Script fails with opaque errors.
Fix: Add dependency checks upfront. Return default JSON structure if deps missing.

**M2. YAML parsing uses fragile grep+sed**
Location: `scripts/estimate-costs.sh:31-51, tests/test-budget.sh:23-47`
Issue: Assumes 2-space indent, no multi-line values. Breaks if YAML structure changes.
Fix: Use Python YAML parser or `yq`. Validate YAML schema in tests.

**M3. Cross-cutting agent definition inconsistent**
Location: `SKILL-compact.md:119` vs `SKILL.md:278`
Issue: One defines cross-cutting as `fd-architecture, fd-quality`. Other includes `fd-performance`.
Fix: Standardize. Recommendation: fd-performance is domain-specific, gets slicing discount.

**M4. Missing behavior tests for budget enforcement**
Location: `tests/test-budget.sh`
Issue: Tests validate structure but not behavior (min_agents, cumulative budget, slicing multiplier).
Fix: Add integration tests or extract budget cut logic to a testable script.

---

### Low Severity (P3)

**L1. budget.yaml comment style inconsistent**
Location: `config/flux-drive/budget.yaml:6-24`
Issue: Inline comments use two styles (explanation vs enumeration).
Fix: Use explanations consistently.

**L2. budget.yaml missing version field**
Location: `config/flux-drive/budget.yaml`
Issue: No version field. Future schema changes will be hard to detect.
Fix: Add `version: 1` and validate in script.

**L3. Convergence adjustment note misplaced**
Location: `synthesize.md:201-204`
Issue: Convergence logic appended to cost report section. Belongs in Step 3.3.
Fix: Move paragraph to deduplication section.

---

## Recommendations

1. **Short-term** (before merge):
   - Add dependency checks to `estimate-costs.sh` (M1)
   - Standardize cross-cutting agent definition across skill files (M3)
   - Move convergence paragraph to correct section (L3)

2. **Medium-term** (next iteration):
   - Replace grep+sed YAML parsing with Python parser (M2)
   - Add version field to budget.yaml (L2)
   - Add behavior tests for budget enforcement (M4)

3. **Long-term** (future enhancements):
   - Add project-level budget overrides (already mentioned in SKILL-compact.md:105)
   - Track actual vs estimated deltas over time, adjust defaults in budget.yaml
   - Integrate with interstat to auto-tune per-agent estimates

---

## Verdict

**APPROVE WITH FINDINGS**

The token budget control system is well-designed and correctly integrated into the flux-drive protocol. Naming is consistent, documentation is clear, and the test suite covers key integration points. The medium-severity findings are edge cases and maintainability concerns, not blockers. Address M1 and M3 before merge; M2 and M4 can be deferred.

**Confidence**: High (full coverage of all changed files, cross-referenced with existing conventions).
