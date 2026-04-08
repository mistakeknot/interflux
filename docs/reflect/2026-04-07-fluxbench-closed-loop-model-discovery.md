---
bead: sylveste-s3z6
date: 2026-04-07
type: reflection
---

# FluxBench Closed-Loop Model Discovery — Reflection

## What Went Well

- **5-wave parallel execution** delivered 12 tasks efficiently. Waves 1-3 each ran fully parallel subagents — scoring engine, calibration, sync, drift, and qualification all built concurrently after their dependencies resolved.
- **TDD paid off**: 24 bats tests caught real issues during development (Python float-to-int serialization, yq v4 syntax differences from Python yq, BATS_TEST_DIRNAME vs BATS_TEST_FILENAME).
- **Quality review caught 2 P0 command injection bugs** (JSON interpolated into Python triple-quoted strings) that tests wouldn't have surfaced. The fix pattern (env vars via `os.environ`) is now established for all bash+Python scripts.

## What Could Improve

- **Shell parameter expansion gotcha**: `${avg_metrics:-{}}` silently appended a literal `}` because the closing brace terminated the expansion early. This produced valid-looking but corrupted JSON. Lesson: always use `"${var:-"{}"}"` with nested quotes for JSON defaults.
- **Registry format mismatch**: `models: []` (empty YAML list) vs `models: {}` (empty dict) caused every Python `.get()` to crash. Should have caught this in the plan — add a "verify target format" step to the registry extension task.
- **Non-atomic writes under flock**: The initial qualify.sh wrote directly to the live registry file inside the flock section. If Python crashed mid-write, the registry would be truncated. Fixed to cp→modify→validate→mv pattern. All new registry writers should follow this.

## Patterns to Reuse

- **Env var data passing**: For any bash script that calls inline Python with untrusted data, always pass via `export _FB_VAR="$data"` + `os.environ['_FB_VAR']` — never interpolate into Python source.
- **Flock fd convention**: fd 200 for JSONL appends, fd 201 for registry writes. Established and documented.
- **Write-once qualified_baseline**: The write-once contract (only qualify.sh sets it, only on null→qualified transition) prevents drift ratchet erosion. Pattern applies to any frozen reference value.

## Metrics

- Tests: 24/24 pass (6 score, 3 calibrate, 5 sync, 5 drift, 5 qualify)
- Scripts: 6 new (score, calibrate, drift, sync, qualify, challenger)
- Configs: 2 new (metrics, thresholds), 3 modified (registry, budget, agent-roles)
- P0s found and fixed: 2 (command injection, eval)
- P1s found and fixed: 4 (non-atomic write, misleading verdict, list format, f-string compat)
