# interflux scripts/ — Conventions

Reference card for shell + Python utilities under `scripts/`. Establishes canonical names and patterns so cross-script edits stay coherent.

## Canonical environment variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `MODEL_REGISTRY` | Path to `model-registry.yaml` | `${PLUGIN_DIR}/config/flux-drive/model-registry.yaml` |
| `BUDGET_CONFIG` | Path to `budget.yaml` | `${PLUGIN_DIR}/config/flux-drive/budget.yaml` |
| `FLUXBENCH_RESULTS_JSONL` | FluxBench results JSONL | `${PLUGIN_DIR}/data/fluxbench-results.jsonl` |
| `CLAUDE_PLUGIN_ROOT` | Plugin root directory (set by Claude Code at runtime) | derived from script location |
| `INTERFLUX_DEBUG` | When set, exception handlers that swallow errors emit a one-line stderr trace | unset |

**Rule:** every script that reads the model registry must respect `MODEL_REGISTRY` as an env override:
```bash
MODEL_REGISTRY="${MODEL_REGISTRY:-${SCRIPT_DIR}/../config/flux-drive/model-registry.yaml}"
```

Older variable names (`REGISTRY_FILE`, `REGISTRY`) were retired in BP-B5 (sylveste-9lp.34); do not reintroduce them.

## flock fd allocation

When multiple scripts share a process and all use `flock(2)` (per-FD locks), fd numbers must not collide across lock domains. The current allocation:

| fd | Lock domain | Lock path | Used by |
|----|-------------|-----------|---------|
| 200 | FluxBench results JSONL | `${FLUXBENCH_RESULTS_JSONL}.lock` | `fluxbench-score.sh`, `fluxbench-qualify.sh` |
| 201 | Model registry | `${MODEL_REGISTRY}.lock` | `lib-registry.sh`, `fluxbench-drift.sh`, `fluxbench-qualify.sh`, `discover-merge.sh` |
| 202 | Sync state | `*.sync.lock` | `fluxbench-sync.sh` |
| 203 | Peer findings JSONL | `${findings_file}.lock` | `findings-helper.sh` |

**Rule:** never reuse an fd across lock domains in the same process. When adding a new lock domain, pick the next free fd and update this table.

## Atomic registry mutations

Use `lib-registry.sh`'s `registry_atomic_mutate` (or its convenience wrappers) for any change to `model-registry.yaml`. It handles:
- 30-second timeout flock on `${MODEL_REGISTRY}.lock` (fd 201)
- `cp` to tmpfile → mutate via `lib_registry.py` CLI → `mv` back (atomic POSIX rename)
- EXIT trap (not RETURN — RETURN doesn't fire on SIGINT or `set -e` exits)
- Structured exit codes: 0 ok, 2 parse error, 3 slug-not-found-or-lock-timeout, 4 invalid invocation

```bash
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib-registry.sh"
registry_atomic_mutate "$MODEL_REGISTRY" set-field <slug> <key> <value-json>
registry_atomic_mutate "$MODEL_REGISTRY" merge-fields <slug> <fields-json>
registry_atomic_mutate "$MODEL_REGISTRY" set-field-if-absent <slug> <key> <value-json>
registry_atomic_mutate "$MODEL_REGISTRY" promote <slug>
registry_set_string_field "$MODEL_REGISTRY" <slug> <key> <plain-string>
registry_validate "$MODEL_REGISTRY"
```

**Do NOT** roll your own copy-paste atomic-mutate scaffolding — five scripts diverged that way before BP-C1 consolidated them. If a needed primitive is missing (e.g., add-model for new entries, top-level-key set), add it to `lib_registry.py` rather than inlining a heredoc.

## Python heredoc size convention

Inline Python heredocs (`python3 -c "..."`) are fine for ≤10 logical lines. Beyond that:

1. Extract to `scripts/_<name>.py` with `if __name__ == "__main__":` CLI.
2. Invoke via `python3 "${SCRIPT_DIR}/_<name>.py" <args>` from the shell wrapper.
3. Add unit tests at `scripts/tests/test_<name>.py`.

The 180-line FluxBench scoring algorithm (BP-C1.C, sylveste-9lp.32.7) was the canonical case: it lived in a `python3 -c` heredoc inside `fluxbench-score.sh` until extraction made it testable. Don't recreate that pattern.

## Python error handling

Use the `_debug(msg, *args)` helper at the top of `flux-agent.py` and `generate-agents.py` for exception handlers that intentionally swallow errors:

```python
try:
    data = yaml.safe_load(text)
except Exception as exc:
    _debug("scope: parse failed: %s", exc)
    return None
```

When `INTERFLUX_DEBUG` is set, the silenced error becomes observable on stderr without polluting normal runs. **Avoid bare `except Exception:` with no handler** — use `_debug()` even if the recovery path is `return None`, so debugging future issues doesn't require git-bisect to find which silent catch is hiding the error.

Where the failure mode is well-known, prefer narrow exception types (e.g. `except (yaml.YAMLError, OSError)`) — but only when the call path is fully understood and adding a new exception class won't silently break recovery.

## Stderr capture

`$(... 2>&1)` captures both stdout and stderr into the variable. This is rarely what you want for Python invocations — a `DeprecationWarning` becomes part of `$result` and breaks the downstream `jq` parse. Use plain `$( ... )` (stderr passes through) and add `2>/dev/null` only for known-noisy commands.

`fluxbench-challenger.sh` previously had two `2>&1` captures that silently broke challenger selection when `yaml.safe_load` emitted a deprecation warning. Fixed in BP-B5.

## VerificationStep — audit primitive for state transitions

`scripts/_verification.py` provides a single-purpose primitive for "we checked and were correct to skip" vs "we never checked" — the gap that erases audit trails on no-op short-circuit paths.

```python
from _verification import VerificationStep, append_to_log

# Three factory constructors, three states:
ok    = VerificationStep.verified("microrouter-passthrough",
                                   "matched B3 calibration:sonnet",
                                   decision_type="passthrough")
bad   = VerificationStep.failed("safety-floor-check",
                                 "fd-safety routed to haiku")
fuzzy = VerificationStep.unverifiable("shadow-log-fetch",
                                       "interspect endpoint unreachable",
                                       decision_type="endpoint-unreachable")

assert ok.is_success() is True
assert bad.is_success() is False
assert fuzzy.is_success() is False   # UNVERIFIABLE != success — fail-closed

append_to_log(ok, "/path/to/decisions.jsonl")
```

**Critical invariant:** `UNVERIFIABLE` is **not** success. When a check can't be performed (missing data, broken tool, endpoint down), downstream code must fail-closed (e.g., privacy-routing must engage local fallback rather than passing through).

`run_uuid` auto-populates from `FLUX_RUN_UUID` env when set (BP-C2.B will wire this through). Output is compact JSONL — no spaces in separators, None fields dropped.

## Decisions log — per-run JSONL audit trail

`scripts/_decisions_log.py` appends decision records to `{OUTPUT_DIR}/decisions.log` (one JSONL line per record) so debugging "why didn't fd-X run?" doesn't require re-reading the orchestrator transcript. Records reuse the `VerificationStep` schema for coherence.

```python
from _decisions_log import log_decision

# Triage
log_decision("triage-rank", "fd-architecture top score 0.87",
             decision_type="triage", score=0.87, slug="fd-architecture")

# Stage-2 expansion
log_decision("stage-2-expansion", "promoted fd-y, fd-z (agreement gap > 0.4)",
             decision_type="expansion", promoted=["fd-y", "fd-z"])

# AgentDropout
log_decision("agent-dropout", "fd-quality dropped (score 0.42 < threshold 0.6)",
             decision_type="dropout", agent="fd-quality", score=0.42)

# Budget cuts
log_decision("budget-cut", "stage-2 reduced from 6 to 4 by token budget",
             decision_type="budget", original=6, final=4, reason="token_ceiling")
```

Shell-side equivalent:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/_decisions_log.py" log <name> <evidence> \
  --decision-type=triage --extra-json='{"score":0.87,"slug":"fd-architecture"}'
```

Both forms read `$FLUX_OUTPUT_DIR` to locate the log; both auto-populate `run_uuid` from `$FLUX_RUN_UUID`. Calls are silent no-ops outside an active flux-drive run (no error if `$FLUX_OUTPUT_DIR` is unset) so callers can invoke unconditionally.

**Canonical decision_type values** (for grep-friendly post-mortems):
- `triage` — agent ranking, knowledge retrieval scoring
- `expansion` — Stage-2 promotion rule, agreement-gap calculation
- `dropout` — AgentDropout threshold cut
- `budget` — Stage budget cap enforcement, slot reduction
- `passthrough` / `override` / `skipped` / `timed-out` / `agent-ineligible` / `endpoint-unreachable` — VerificationStep state-transition decisions (see VerificationStep section above)

`_decisions_log.read_log(output_dir)` returns the parsed records for inspection (testing + post-mortem).

## run_uuid quire-mark

Every flux-drive run generates a UUID in launch.md Phase 2.0:
```bash
FLUX_RUN_UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
export FLUX_RUN_UUID
export FLUX_OUTPUT_DIR="{OUTPUT_DIR}"
```

Three downstream consumers:
1. **`_verification.py`** — every `VerificationStep` auto-records `run_uuid` from the env var, so audit logs trace back to their originating run.
2. **`_decisions_log.py`** — every decision record carries the same UUID.
3. **Agent output preamble** — `references/prompt-template.md` requires agents to emit `<!-- run-uuid: {RUN_UUID} -->` as the first non-empty line of their output. Synthesis (`phases/synthesize.md` Step 3.1) classifies any agent file with a missing or mismatched UUID as **Foreign** and skips it, preventing stale outputs from prior runs (or files written by a concurrent invocation into the same content-addressed OUTPUT_DIR) from contaminating the synthesis.

The "quire-mark" name is from medieval bookbinding: every page in a quire was marked with the same signature so the binder could detect mis-bound pages from another quire. Same idea — every artifact in a run gets the same opaque tag.

## Dispatch state machine + retry race

Documented in `skills/flux-drive/phases/shared-contracts.md` § Dispatch State Machine. Six states (`dispatched`, `writing`, `completed`, `timeout_original_running`, `retried`, `failed`) and explicit invariants. The retry race protocol (BP-C2) renames the original Task's `.md.partial` to `.md.partial.aborted-<epoch>` before launching a synchronous retry — the original's eventual `mv .partial → .md` finds no source and fails harmlessly. `flux-watch.sh` filters `.aborted-*` and `.abort` files from completion counts.

## Test runner

```bash
python3 -m pytest scripts/tests/ -v
```

Currently 135 tests across `test_lib_registry.py` (53), `test_fluxbench_score.py` (39), `test_verification.py` (26), and `test_decisions_log.py` (17). New extracted modules under `scripts/_*.py` should ship with a matching `scripts/tests/test_<module>.py`.
