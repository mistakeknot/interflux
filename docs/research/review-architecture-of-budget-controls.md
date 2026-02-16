# Architecture Review: Token Budget Controls for Flux-Drive

**Reviewed**: 2026-02-16
**Reviewer**: fd-architecture (Flux-drive Architecture & Design Reviewer)
**Scope**: Integration of token budget controls into flux-drive agent dispatch protocol

---

## Executive Summary

The budget-aware triage addition integrates cleanly with the existing flux-drive protocol. The design respects phase boundaries, uses proper fallback paths, and maintains protocol conformance. Two structural concerns require attention: interstat coupling creates an implicit dependency that violates plugin independence, and the budget cut algorithm's placement after stage assignment creates a stage-budget interaction that needs explicit documentation.

**Verdict**: Needs changes (P1 issues)

---

## Findings

### P0 — Critical Structural Issues

None.

### P1 — Important Design Issues

#### P1-1. Implicit dependency on interstat violates plugin independence

**Location**: `scripts/estimate-costs.sh:69-86`, `SKILL-compact.md:117-119`, `synthesize.md:148-161`

**Issue**: The budget system queries interstat's SQLite database directly using hardcoded paths (`~/.claude/interstat/metrics.db`). This creates a compile-time dependency on interstat's schema without declaring it in plugin.json or handling installation order.

**Evidence**:
- `estimate-costs.sh` queries `agent_runs` table with no schema version check
- `synthesize.md` Step 3.4b.1 inlines SQL queries directly into the skill instructions
- `SKILL-compact.md` references "interstat, >= 3 runs" but interflux's plugin.json does not list interstat as a dependency

**Impact**:
- If interstat changes its schema (renames `agent_runs`, adds required columns), estimate-costs.sh breaks silently
- If interstat is not installed, the script degrades gracefully (good) but users get no warning that they're missing cost optimization data
- Direct SQL coupling makes it impossible to version-lock the interstat contract

**Why it matters**: Plugins in the Interverse ecosystem should declare dependencies explicitly. The flux-drive spec is framework-agnostic, but the interflux implementation creates a hidden coupling that violates plugin composability.

**Recommended fix**:
1. Wrap interstat queries behind an abstraction: `interstat-query.sh` that checks for plugin installation, schema version, and provides a stable interface
2. Add interstat to plugin.json as an optional dependency with schema version contract
3. Document the degradation path: "Without interstat: uses defaults from budget.yaml, no learning over time"
4. Consider: Could interstat provide an MCP tool for token estimation? This would version-lock the interface and make cross-plugin reuse cleaner.

**Convergence**: This is a single-agent finding; no other agents reviewed coupling patterns.

---

#### P1-2. Budget cut algorithm interacts with stage assignment in undocumented ways

**Location**: `SKILL-compact.md:121-137`, diff hunk for Step 1.2c.3

**Issue**: The budget cut happens AFTER stage assignment (Step 1.2b assigns stages, Step 1.2c.3 applies budget cut). The note "If all Stage 1 agents fit within budget but adding Stage 2 would exceed it, mark Stage 2 as 'Deferred (budget)'" describes a policy, but the algorithm in Step 1.2c.3 just walks sorted agents and cuts when budget is exceeded. There's no explicit handling of the Stage 1/Stage 2 boundary.

**Evidence**:
```
# From SKILL-compact.md:125-133
for agent in sorted_agents:
    if cumulative + agent.est_tokens > BUDGET_TOTAL and agents_selected >= min_agents:
        agent.action = "Deferred (budget)"
    else:
        agent.action = "Selected"
        cumulative += agent.est_tokens
```

This loop doesn't check `agent.stage`. If stages are interleaved by score (e.g., Stage 1 agent at rank 5, Stage 2 agent at rank 4), the budget cut could defer a Stage 1 agent while selecting a Stage 2 agent.

**Impact**:
- The note at line 137 ("Stage interaction: If all Stage 1 agents fit...") implies Stage 1 agents are protected, but the algorithm doesn't enforce this
- If domain agents (always Stage 1 per core/scoring.md) have low scores, they could be budget-deferred, breaking the "domain agents always in Stage 1" guarantee from the spec

**Why it matters**: Stage assignment is a protocol-level concept (core/staging.md). Budget is an implementation detail. The two should compose cleanly: either budget respects stage boundaries (Stage 1 always selected, Stage 2 is the cut zone), or stages are advisory and budget is absolute. The current design is ambiguous.

**Recommended fix**:
1. Clarify the policy: "Budget cuts Stage 2 first. If budget is tight, defer lower-scoring Stage 2 agents before touching Stage 1."
2. Update algorithm to enforce: partition agents into Stage 1 and Stage 2 lists, accumulate Stage 1 fully, then add Stage 2 until budget is exceeded.
3. Alternatively: Document that stages are score-based only, and budget cuts by absolute score regardless of stage. Then remove the "Stage interaction" note or rewrite it to match reality.

**Convergence**: Single-agent finding.

---

### P2 — Minor Issues

#### P2-1. estimate-costs.sh uses sed for YAML parsing when grep suffices

**Location**: `scripts/estimate-costs.sh:36-40`

**Issue**: The `get_default()` function uses `grep` + `sed` to extract values from budget.yaml. The sed pattern `'s/.*: *//'` is fragile if YAML values contain colons (e.g., `review: "foo:bar"`). In this case it's safe (all values are integers), but it's a latent bug.

**Fix**: Use `awk '{print $2}'` or add a yq/jq conversion step if YAML complexity grows.

**Severity**: P2 (works now, could break if budget.yaml schema evolves).

---

#### P2-2. No explicit cache invalidation for budget config changes

**Location**: `SKILL-compact.md:105` (project override), `budget.yaml` (plugin-level defaults)

**Issue**: If a user updates `.claude/flux-drive-budget.yaml` mid-session, the change won't take effect until the next flux-drive invocation. This is probably fine (config is read per-invocation), but there's no documentation of when config is loaded.

**Fix**: Add a note in AGENTS.md: "Budget config is loaded once per flux-drive invocation. Changes take effect on the next run."

**Severity**: P2 (UX clarity, not a functional bug).

---

### Improvements

#### IMP-1. Cost report could show per-stage token distribution

**Rationale**: The cost report in synthesize.md Step 3.5 shows per-agent tokens but doesn't aggregate by stage. For large reviews, seeing "Stage 1: 80K, Stage 2: 120K" would help users understand where tokens are going.

**Suggested addition** to findings.json schema:
```json
"cost_report": {
  "by_stage": {
    "stage_1": {"agents": 3, "estimated": 80000, "actual": 75000},
    "stage_2": {"agents": 2, "estimated": 120000, "actual": 110000}
  }
}
```

**Impact**: Better token attribution for multi-stage reviews.

---

#### IMP-2. Slicing multiplier (0.5) is hardcoded and untested

**Rationale**: `budget.yaml:26` sets `slicing_multiplier: 0.5`, meaning sliced agents use 50% of their normal estimate. This is reasonable (agents see less content), but there's no evidence this is calibrated. After 10-20 sliced reviews, interstat will have real data. Consider adding a "calibration review" step after N sliced reviews to adjust the multiplier.

**Suggested addition** to AGENTS.md Measurement Definitions:
> **Slicing multiplier accuracy**: Compare actual tokens for sliced vs full-document reviews to validate the 0.5 factor. Update budget.yaml if median delta exceeds ±20%.

---

#### IMP-3. Budget enforcement mode is "soft" with no "hard" implementation

**Rationale**: `budget.yaml:32` has `enforcement: soft` (warn + offer override). The diff mentions "hard = block", but there's no code path that reads this field or enforces it. Either implement hard mode or remove the comment.

**Impact**: Dead code / future promise. Either commit to implementing it (useful for CI pipelines where token budgets are strict) or document it as "reserved for future use."

---

## Boundaries & Coupling Analysis

### Module Boundaries

| Module | Responsibility | Boundary Crossings |
|--------|---------------|-------------------|
| `config/flux-drive/budget.yaml` | Token budget config (data) | Read by estimate-costs.sh, skill instructions |
| `scripts/estimate-costs.sh` | Cost estimation (query interstat + defaults) | Queries interstat DB, reads budget.yaml |
| `SKILL.md` / `SKILL-compact.md` | Orchestration logic | Invokes estimate-costs.sh, applies budget cut |
| `phases/synthesize.md` | Post-review analysis | Queries interstat DB directly |
| `tests/test-budget.sh` | Structural validation | Reads budget.yaml, runs estimate-costs.sh |

**Clean boundaries**:
- budget.yaml is pure config (no logic)
- estimate-costs.sh is a pure function (deterministic given DB state)
- test-budget.sh validates structure, doesn't test behavior

**Boundary violations**:
- **synthesize.md directly queries interstat DB** (lines 150-159) — should use estimate-costs.sh or a shared query module
- **No abstraction layer between flux-drive and interstat schema** — tightly coupled SQL queries

**Recommendation**: Extract a `lib-interstat.sh` shared script:
```bash
# lib-interstat.sh
query_agent_tokens() {
  local session_id="$1"
  local agent_name="$2"
  sqlite3 -json ~/.claude/interstat/metrics.db "SELECT ... WHERE session_id='$session_id' AND agent_name='$agent_name';"
}

query_avg_tokens() {
  local agent_name="$1"
  local model="$2"
  sqlite3 -json ~/.claude/interstat/metrics.db "SELECT AVG(...) FROM agent_runs WHERE agent_name='$agent_name' AND model='$model' GROUP BY agent_name HAVING COUNT(*) >= 3;"
}
```

Then both estimate-costs.sh and synthesize.md call these functions. If interstat schema changes, only lib-interstat.sh needs updates.

---

### Dependency Direction

```
flux-drive skill (orchestrator)
  ↓ reads
budget.yaml (config)
  ↓ invokes
estimate-costs.sh (query layer)
  ↓ queries
interstat SQLite DB (data layer)
```

**Correct direction**: High-level orchestrator depends on low-level data. Budget config is injected (can be overridden per-project).

**Issue**: No version contract between estimate-costs.sh and interstat. If interstat is a separate plugin (which it is), this is cross-plugin coupling without a declared interface.

**Recommended fix**: Add to interflux's plugin.json:
```json
"dependencies": {
  "interstat": {
    "optional": true,
    "schema_version": 1,
    "fallback": "Uses default cost estimates from budget.yaml"
  }
}
```

And in interstat's AGENTS.md, document the query contract:
```markdown
## Query Contract (for consumers)

Interstat provides a SQLite database at `~/.claude/interstat/metrics.db` with the following stable schema:

- Table: `agent_runs`
- Required columns: `agent_name`, `model`, `input_tokens`, `output_tokens`
- Schema version: Tracked via `PRAGMA user_version`
- Consumers MUST check `user_version >= 1` before querying
```

---

### Pattern Analysis

#### Good Patterns

1. **Graceful degradation**: estimate-costs.sh handles missing DB cleanly (lines 67-86)
2. **Config override hierarchy**: Plugin defaults → project overrides (SKILL-compact.md:105)
3. **Separation of estimation and enforcement**: estimate-costs.sh is pure (no side effects), skill applies policy
4. **Structured test suite**: test-budget.sh validates config schema, script output, and skill references

#### Concerning Patterns

1. **SQL in skill instructions**: synthesize.md Step 3.4b.1 embeds raw SQL. This breaks abstraction and makes schema changes error-prone.
2. **Hardcoded paths**: `~/.claude/interstat/metrics.db` appears in 3 places (estimate-costs.sh, synthesize.md, test-budget.sh). Should be a constant or env var.
3. **Stage-budget interaction implicit**: The relationship between Stage 1/2 and budget cuts is described in prose but not enforced by code structure.

---

### Integration with Existing Protocol

The budget controls integrate at **Phase 1, Step 1.2c** (after scoring, before user confirmation). This is the right place: triage is deterministic up to Step 1.2b, then budget constraints are applied, then the user sees the final roster.

**Protocol conformance check** (against flux-drive-spec 1.0):

| Requirement | Status | Evidence |
|-------------|--------|----------|
| 3-phase lifecycle preserved | ✅ Pass | Budget is Phase 1 only, doesn't affect Phase 2 launch or Phase 3 synthesis |
| Agent scoring not modified | ✅ Pass | Budget cut happens after scoring; scores are unchanged |
| Stage assignment precedes budget | ⚠️ Ambiguous | Stages assigned in 1.2b, budget cut in 1.2c, but cut algorithm doesn't respect stages |
| Findings Index format unchanged | ✅ Pass | Budget only affects which agents launch, not their output format |
| User approval gate extended | ✅ Pass | Adds "Launch all (override budget)" option, backward-compatible |

**Conformance level**: Still "flux-drive-spec 1.0 Core + Domains" — budget controls are an internal optimization, not a protocol extension.

**Extension potential**: If budget controls prove valuable, they could become "flux-drive-spec 1.1 + Budget" conformance level. Current design is a good prototype.

---

## Complexity Assessment

### Added Complexity

| Component | Before | After | Delta |
|-----------|--------|-------|-------|
| Triage step count | 1.2a, 1.2b, 1.3 | 1.2a, 1.2b, 1.2c (3 substeps), 1.3 | +1 step, +3 substeps |
| Config files | domains/, knowledge/ | domains/, knowledge/, budget.yaml | +1 file |
| Scripts | detect-domains.py, validate-roster.sh | + estimate-costs.sh | +1 script |
| Test files | (none for triage) | test-budget.sh | +1 test suite |
| AGENTS.md sections | (various) | + Measurement Definitions | +38 lines |

**Complexity justified?** Yes. Token budgets are a real constraint for production use. The added complexity is localized (Step 1.2c, one script, one config file) and doesn't leak into Phase 2/3.

**Could it be simpler?** Possibly:
- Remove interstat integration, use defaults only → simpler, but loses learning over time
- Hardcode budgets per input type → simpler, but less flexible
- Skip per-agent estimates, use total budget only → simpler, but can't explain triage decisions

Current design is near-minimal for the feature set.

---

### Cognitive Load for Skill Executors

The budget cut adds **one decision point** to triage:
1. Score agents (existing)
2. **NEW**: Accumulate estimated tokens, defer agents over budget
3. Present roster to user (extended with budget summary)

For users:
- Triage table adds 2 columns: "Est. Tokens", "Source"
- Budget summary line shows cumulative / total
- Override option if agents deferred

**Impact**: Low. Budget context is helpful (explains why an agent was deferred). The default behavior (respect budget) is safe.

---

## Simplicity & YAGNI Review

### Necessary Complexity

- **Budget config**: Yes. Different input types (PRD vs repo) have different token profiles.
- **Per-agent estimates**: Yes. Enables ranked selection (defer expensive low-value agents first).
- **Interstat integration**: Maybe. Could start with defaults-only, add learning later.
- **Slicing multiplier**: Yes. Sliced agents objectively see less content.
- **Project overrides**: Yes. Some projects have strict token budgets (CI pipelines), others don't care.

### Speculative Complexity

- **Enforcement mode (soft/hard)**: Field exists but isn't used. Remove or implement.
- **Cost report in findings.json**: Useful for debugging, but could be opt-in (add `--verbose` flag).
- **Sample size tracking**: estimate-costs.sh tracks "N runs" but doesn't use it for confidence weighting. Could just check `>= 3` as a binary.

### Recommended Deletions

1. Remove `enforcement` field from budget.yaml until hard mode is implemented (YAGNI)
2. Simplify estimate-costs.sh output: drop `sample_size` from JSON unless it affects decisions

### Recommended Consolidations

1. Merge `SKILL.md` and `SKILL-compact.md` Step 1.2c sections — they're identical except for formatting
2. Extract interstat queries into a shared lib (reduces duplication between estimate-costs.sh and synthesize.md)

---

## Risk Assessment

### Integration Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Interstat schema change breaks queries | Medium | High | Add schema version check, abstract queries |
| Budget cut defers critical agents | Low | Medium | `min_agents` guarantees top 2; domain agents should be high-scoring |
| Project overrides misconfigured | Low | Low | test-budget.sh validates syntax; bad values just defer agents |
| Cost estimates wildly inaccurate | Medium | Low | Graceful degradation: over-budget launches fewer agents, under-budget launches more |

### Rollout Risks

- **Existing flux-drive users**: Budget controls are additive. Default budgets are generous (150K for plans, 300K for repos). Users shouldn't notice unless they have 10+ agents.
- **New users**: Triage table is more complex (2 extra columns). Budget summary line is helpful context.
- **CI/CD pipelines**: If token budgets matter, project overrides are mandatory. No auto-detection.

**Recommendation**: Ship with `enforcement: soft` (warn but allow override). Monitor for false positives (useful agents deferred). After 20-30 reviews, calibrate budgets and consider adding `enforcement: hard` mode.

---

## Recommendations Summary

### Must Fix (P1)

1. **Declare interstat dependency** in plugin.json and abstract SQL queries
   - Add `lib-interstat.sh` or use MCP tool if available
   - Schema version check before querying
   - Document degradation path in AGENTS.md

2. **Clarify stage-budget interaction**
   - Either enforce "Stage 1 protected" or document "budget cuts by score, stages are advisory"
   - Update SKILL-compact.md algorithm to match policy

### Should Fix (P2)

3. Replace sed with awk/yq for YAML parsing
4. Document when budget config is loaded (per-invocation, not cached)

### Consider (Improvements)

5. Add per-stage token breakdown to cost report
6. Calibrate slicing multiplier after N reviews
7. Implement `enforcement: hard` or remove the field

---

## Conclusion

The budget-aware triage design is sound. It integrates cleanly into Phase 1, respects existing protocol boundaries, and adds useful functionality without breaking backward compatibility. The two P1 issues (interstat coupling, stage-budget ambiguity) are architectural housekeeping — they don't block the feature but should be addressed before the feature is considered "stable."

The addition of Measurement Definitions to AGENTS.md is excellent — it establishes a shared vocabulary for token accounting across the Interverse ecosystem.

**Confidence**: High. This review covered all changed files, cross-referenced the flux-drive spec, and traced data flow from config → script → skill → synthesis.

---

## Files Reviewed

- `config/flux-drive/budget.yaml` (new)
- `scripts/estimate-costs.sh` (new)
- `tests/test-budget.sh` (new)
- `AGENTS.md` (Measurement Definitions section)
- `skills/flux-drive/SKILL.md` (Step 1.2c reference)
- `skills/flux-drive/SKILL-compact.md` (Step 1.2c full algorithm)
- `skills/flux-drive/phases/synthesize.md` (Step 3.4b cost report)
- Diff hunks provided in task prompt

**Related context**:
- `docs/spec/core/protocol.md` (phase boundaries)
- `docs/spec/core/scoring.md` (stage assignment)
- `docs/spec/core/staging.md` (Stage 1/2 semantics)
- Interstat plugin schema (`agent_runs` table)
