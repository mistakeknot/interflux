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

## Test runner

```bash
python3 -m pytest scripts/tests/ -v
```

Currently 92 tests across `test_lib_registry.py` (53) and `test_fluxbench_score.py` (39). New extracted modules under `scripts/_*.py` should ship with a matching `scripts/tests/test_<module>.py`.
