# Quality Review: mcp_agent_mail

**Reviewer:** fd-quality (flux-drive Quality & Style)
**Target:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/`
**Date:** 2026-02-24
**Scope:** Python/FastMCP server — 14 source files, ~29k lines, ~47 MCP tools, ~110 test files

---

## Executive Summary

This is a well-engineered codebase with excellent infrastructure foundations: frozen dataclasses for settings, async context managers throughout, proper `from exc` exception chaining at all translation points, a coherent circuit-breaker in `db.py`, FTS5 integration with query sanitization, and an instrumentation wrapper that unifies retry, metrics, and logging. The test suite is exceptionally thorough (~110 files, integration + concurrency + E2E scenarios).

The primary structural concern is `app.py` at 11,382 lines containing all 47 tool definitions, all business logic, all helper infrastructure, and all MCP resource endpoints in a single file. This is the dominant finding because it has direct team-velocity impact. Secondary concerns are addressed below.

**Patterns worth adopting in Demarch codebases:** `_instrument_tool` wrapper pattern, frozen dataclass settings, `cast(Any, ...)` with explicit comment for SQLAlchemy type workarounds, `contextvars` for per-request query tracking, lifespan factory pattern.

**Anti-patterns to avoid:** The `format` parameter approach, bare `except Exception:` swallowing errors silently, duplicate helper definitions, inline `import` inside exception handlers.

---

## Finding 1 — CRITICAL: app.py is a 11,382-line monolith

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/app.py`
**Lines:** 1–11,382

`app.py` contains everything: the `ToolExecutionError` exception class, the `_instrument_tool` decorator, EMFILE retry logic, output format handling, FTS query sanitization, project identity resolution (~400 lines), file reservation staleness checking (~200 lines), sibling project suggestion LLM scoring, all 47 MCP tool definitions, all MCP resource endpoints (~30), and two post-registration filter functions. The `build_mcp_server()` factory function alone spans approximately lines 4306–11342, making the file's logical structure invisible without a search tool.

`send_message` is ~997 lines by itself — it contains contact enforcement, thread participant lookup, file reservation overlap detection, auto-handshake orchestration, broadcast logic, archive writing, and notification signaling all inlined. This is not a tool; it is a subsystem.

**Impact:** Onboarding requires reading all 11k lines to understand where a given behavior lives. Merge conflicts are guaranteed. Finding where to add a new tool or change a policy requires grep. The `build_mcp_server` closure wraps all tool functions, which prevents individual tool testing without constructing the entire server.

**Recommended split:**

```
src/mcp_agent_mail/
  app.py              # Only: FastMCP setup, build_mcp_server(), tool filter
  errors.py           # ToolExecutionError, error type constants
  instrument.py       # _instrument_tool decorator, TOOL_METRICS, RECENT_TOOL_USAGE
  output_format.py    # format param resolution, _encode_payload_to_toon_sync
  identity.py         # _compute_project_slug, _resolve_project_identity, _norm_remote
  projects.py         # _ensure_project, _get_project_by_identifier, sibling suggestions
  agents.py           # _get_or_create_agent, _get_agent, _get_agents_batch, name validation
  messaging.py        # _deliver_message, _create_message, _list_inbox, _list_outbox
  file_reservations.py # reservation CRUD, staleness, conflict detection
  tools/
    identity_tools.py   # health_check, ensure_project, register_agent, whois, ...
    messaging_tools.py  # send_message, reply_message, fetch_inbox, ...
    reservation_tools.py
    macro_tools.py
    search_tools.py
    product_tools.py
```

The `_instrument_tool` decorator is a clean seam; the tool functions themselves have no circular dependency on the business logic — they just call helpers. The split is mechanical.

---

## Finding 2 — HIGH: `format` parameter on 68 call sites is a design smell

**Files:** `app.py` (all tool and resource definitions)

Every tool and resource endpoint carries `format: Optional[str] = None`. This is 68 occurrences in `app.py` alone. The parameter exists to select between `json` (default) and `toon` (a token-efficient encoding) output formats.

Problems with the current approach:

1. **It pollutes every tool's public schema.** MCP tool schemas are surfaced to AI agents as JSON Schema. Adding a non-domain parameter to 47 tools means every agent sees `format` alongside `project_key`, `agent_name`, etc. This inflates context and creates confusion: agents may pass `format='toon'` on write tools where the parameter does nothing meaningful.

2. **The `format` parameter shadows Python's built-in `format()` function.** This is why `# ruff: noqa: A002` is applied file-wide. Suppressing a linter rule for the entire 11k-line file to accommodate one parameter name is disproportionate.

3. **The parameter is not enforced by the type system.** It accepts `Optional[str]` and silently ignores invalid values. The actual validation happens inside `_resolve_output_format`, not at the tool boundary.

4. **The cross-cutting concern belongs in transport, not tool definitions.** HTTP transport layers (e.g., Accept headers, query parameters) are the conventional place for format negotiation. For MCP specifically, the `MCP_AGENT_MAIL_OUTPUT_FORMAT` environment variable already provides a server-wide default — that mechanism alone covers 99% of use cases.

**Recommended approach:** Remove `format` from all tool signatures. Keep only the server-wide `MCP_AGENT_MAIL_OUTPUT_FORMAT` env var. If per-call format selection is genuinely needed for a subset of tools, implement it via a dedicated MCP resource or a wrapper resource layer, not as a tool parameter. As a minimum, rename the parameter to `output_format` to avoid shadowing the built-in and remove the file-wide noqa suppression.

```python
# Current — appears 68 times:
format: Optional[str] = None

# If retained, rename to avoid built-in shadow:
output_format: Optional[str] = None
```

---

## Finding 3 — HIGH: 122 bare `except Exception:` silently swallow failures

**File:** `app.py`
**Pattern count:** 122 occurrences of `except Exception:` with no re-raise and no structured logging

Representative examples:

```python
# Line 438 — inside _instrument_tool's logging path
except Exception:
    # Logging errors should not break tool execution
    log_ctx = None

# Line 673
except Exception:
    # Logging errors should not suppress original exceptions
    pass

# Line 1619 — _rich_error_panel
except Exception:
    return

# Line 1650 — _render_commit_panel
except Exception:
    return None
```

The "logging must not break tool execution" rationale is valid for the two cases inside `_instrument_tool`. But the pattern has propagated to business logic paths. In `_resolve_project_identity` (lines 1739–2109), multiple `except Exception: pass` blocks skip git operations silently — if GitPython raises an unexpected error (e.g., corrupted config), the identity falls back to `dir` mode with no visibility.

In `send_message` (lines 5697–6231), several `except Exception: logger.exception(...)` calls correctly log but do not re-raise. However, there are inner `except Exception: pass` blocks that silently ignore auto-handshake failures — which means a contact enforcement failure can go completely unrecorded.

**Concrete fix pattern:** For infrastructure fallbacks (git, logging), the bare except is acceptable but should include a `logger.debug` at minimum:

```python
# Before
except Exception:
    pass

# After
except Exception:
    logger.debug("git_identity.fallback", exc_info=True)
```

For business logic paths that catch-and-continue, the exception should always be recorded:

```python
# Before (line 5698)
except Exception:
    logger.exception("Failed to fetch thread participants ...")

# This is already correct — the pattern to propagate, not fix
```

The issue is the 80+ cases that are neither of the above — they silently drop exceptions in non-logging contexts with no trace.

---

## Finding 4 — MEDIUM: Duplicate `_norm_remote` helper defined twice

**File:** `app.py`, lines 1739 and 1882

```python
# Line 1739 — inside _compute_project_slug, mode == "git-remote" branch
def _norm_remote(url: str | None) -> str | None: ...

# Line 1882 — inside _resolve_project_identity (a separate top-level helper)
def _norm_remote(url: Optional[str]) -> Optional[str]: ...
```

These two nested functions implement the same URL normalization logic with slight differences: the first uses `url.split("@", 1)`, the second uses `at_pos = u.find("@")` with more robust multiprotocol handling. The second is clearly the more complete version.

**Impact:** When the logic needs updating (new git hosting providers, SSH URL edge cases), one copy gets updated and the other drifts. The divergence is already present: the second handles `git+ssh://` prefix checks that the first misses.

**Fix:** Extract to a module-level `_normalize_git_remote_url(url: str | None) -> str | None` function in `identity.py` (or the equivalent after the split recommended in Finding 1) and call it from both sites.

---

## Finding 5 — MEDIUM: `cast(Any, ...)` used 246 times as a SQLAlchemy type workaround

**File:** `app.py`
**Count:** 246 occurrences

```python
# Example pattern — appears hundreds of times:
result = await session.execute(
    select(Agent).where(
        cast(Any, Agent.project_id == project.id),
        cast(Any, func.lower(Agent.name) == desired_name.lower()),
    )
)
```

The file-level comment explains this correctly: "ty currently struggles to type SQLModel-mapped SQLAlchemy expressions." The `cast(Any, ...)` pattern is a legitimate workaround for a known limitation of the `ty` type checker with SQLModel.

However, 246 occurrences creates significant visual noise and is inconsistent — some `where()` calls use `cast(Any, ...)` on every clause, others don't:

```python
# Inconsistent — some clauses wrapped, some not:
.where(
    cast(Any, FileReservation.project_id) == project_id,
    cast(Any, FileReservation.released_ts).is_(None),
    cast(Any, FileReservation.expires_ts) < naive_now,
)

# vs.
.where(Message.project_id == project.id, Message.sender_id == agent.id)
```

**Recommendation:** Document the SQLModel/ty limitation in one place (already done in the file comment). Consider introducing a project-level `mypy.ini` or `pyrightconfig.json` override that ignores SQLModel expression types in `app.py` entirely, eliminating the per-clause visual noise. Alternatively, extract a typed `_where` helper that applies the cast uniformly. The inconsistency is the real issue — a codebase convention either requires `cast(Any, ...)` everywhere or nowhere.

---

## Finding 6 — MEDIUM: Tool naming inconsistency — function name vs registered name

**File:** `app.py`, line 8638

```python
@mcp.tool(name="release_file_reservations")
async def release_file_reservations_tool(...):
```

This is the only tool where the Python function name (`release_file_reservations_tool`) differs from the registered MCP tool name (`release_file_reservations`). All other tools follow the convention where the function name matches the tool name. The `_tool` suffix was added to avoid a conflict with an internal `release_file_reservations` variable used elsewhere in the function.

**Impact:** Minor, but it violates the otherwise consistent pattern. When searching for `release_file_reservations` in the codebase, the function does not appear by that name.

**Fix:** Rename the internal variable (`release_tool` is already used at line 7476 for a cast) to something that does not conflict, then rename the function to `release_file_reservations`.

---

## Finding 7 — MEDIUM: Inline `import errno` inside exception handlers

**File:** `app.py`, lines 449 and 584

```python
# Line 449 — inside _instrument_tool wrapper
except OSError as exc:
    import errno
    if exc.errno == errno.EMFILE ...

# Line 584 — second OSError handler
except OSError as exc:
    import errno
    ...
```

`errno` is part of the standard library and has zero import cost after the first import (Python caches modules). The deferred import pattern here provides no benefit and adds visual confusion. The standard pattern is a top-level import.

**Fix:** Add `import errno` to the top-level import block alongside the other stdlib imports.

---

## Finding 8 — LOW: Settings contains string enum fields without enum types

**File:** `config.py`

Multiple `Settings` fields are `str` with inline comments documenting valid values:

```python
project_identity_mode: str  # "dir" | "git-remote" | "git-common-dir" | "git-toplevel"
ack_escalation_mode: str  # "log" | "file_reservation"
agent_name_enforcement_mode: str  # "strict" | "coerce" | "always_auto"
```

The validation happens in `get_settings()` via local `_agent_name_mode()`, `_tool_filter_profile()`, etc. functions that coerce invalid inputs to defaults without raising errors.

**Impact:** Invalid configuration (e.g., `PROJECT_IDENTITY_MODE=git_remote` with underscore instead of hyphen) silently falls through to a different mode. There is no startup warning.

**Recommendation:** Use `Literal["dir", "git-remote", "git-common-dir", "git-toplevel"]` type annotations. The `dataclass(frozen=True)` already prevents mutation; Literal types let mypy catch bad values at construction. At minimum, add a `logger.warning` in each coercion function when it falls back to a default:

```python
def _agent_name_mode(value: str) -> str:
    v = (value or "").strip().lower()
    if v in {"strict", "coerce", "always_auto"}:
        return v
    if v:  # non-empty but unrecognized
        logger.warning("Unknown agent_name_enforcement_mode %r, defaulting to 'coerce'", value)
    return "coerce"
```

---

## Finding 9 — LOW: Docstring coverage inconsistent across tools

Most tool docstrings are excellent — they follow NumPy-style sections (`When to use`, `Parameters`, `Returns`, `Examples`, `Pitfalls`) and are detailed enough to guide an LLM agent. However, several tools have minimal or absent docstrings:

- `purge_old_messages` (line 6386): one-liner only
- `deregister_agent` (line 4839): short, no examples
- `acquire_build_slot`, `renew_build_slot`, `release_build_slot`: brief one-liners
- `products_link` (line 9290): no Parameters section

This inconsistency matters because docstrings are surfaced directly to AI agents as tool descriptions. A tool with a one-liner description forces the agent to experiment rather than follow documented semantics.

**Recommendation:** Apply the `When to use / Parameters / Returns / Examples` template to the ~6 undertested tools. The existing tools provide an excellent template.

---

## Finding 10 — LOW: Test isolation fixture is comprehensive but conftest cleanup is fragile

**File:** `tests/conftest.py`

The `isolated_env` fixture properly:
- Sets all required env vars via `monkeypatch`
- Calls `reset_database_state()` before and after
- Clears `repo_cache` and settings cache

However, the cleanup code at lines 119–156 uses `gc.get_objects()` to find and close leaked `Repo` instances:

```python
for obj in gc.get_objects():
    if isinstance(obj, Repo):
        with contextlib.suppress(Exception):
            obj.close()
```

This pattern is fragile: `gc.get_objects()` returns all live Python objects and is O(n) with heap size. Under pytest-xdist or when running the full 110-file suite, this adds measurable overhead per test. It also cannot close `Repo` objects that are referenced from live closures (they won't be GC'd).

The root cause is `_open_repo_if_available` in `app.py` (line 1291) which creates `Repo` objects outside the `_git_repo` context manager and returns them to callers. If a caller forgets to close them, they leak. The existing `_git_repo` context manager (line 136) is the correct pattern.

**Recommendation:** Audit all `Repo(...)` direct construction sites in `app.py` that do not use `_git_repo`. Convert them to use the context manager. This eliminates the need for GC-based leak detection in the test fixture.

---

## Patterns Worth Adopting in Demarch Codebases

### 1. `_instrument_tool` wrapper as a cross-cutting concerns aggregator

The decorator pattern at lines 378–687 cleanly handles metrics, retry, capability enforcement, logging, and error translation in one place. Tool functions stay focused on business logic. Go codebases can achieve the same via a middleware wrapper function that accepts the tool handler.

```python
# Pattern:
@_instrument_tool("tool_name", cluster=CLUSTER_X, complexity="low")
async def my_tool(ctx: Context, arg: str) -> dict[str, Any]:
    # Pure business logic only
    ...
```

### 2. Frozen dataclass settings with typed sub-groups

`config.py` uses `@dataclass(slots=True, frozen=True)` for all settings groups, with `@lru_cache(maxsize=1)` on `get_settings()`. The sub-grouping (`HttpSettings`, `DatabaseSettings`, etc.) is clean — each group has a clear conceptual boundary.

### 3. `contextvars.ContextVar` for per-request tracking

`db.py` uses `_QUERY_TRACKER: ContextVar["QueryTracker | None"]` to attach per-request query stats without threading issues. This is idiomatic Python async — each asyncio task gets its own context. Directly applicable to any async Python service that needs per-request instrumentation.

### 4. Explicit `IntegrityError` handling for idempotent creates

Throughout `app.py`, concurrent `INSERT` races are handled correctly:

```python
try:
    await session.commit()
except IntegrityError:
    await session.rollback()
    # Fetch the row that won the race
    project = result.scalars().first()
    if project:
        return project
    raise  # Unexpected — re-raise
```

This pattern (insert → catch IntegrityError → refetch) is correct for concurrent idempotent creation. The `raise` on re-fetch failure preserves failure context correctly.

### 5. `_git_repo` context manager for GitPython resource safety

```python
@contextlib.contextmanager
def _git_repo(path: str | Path, search_parent_directories: bool = True) -> Any:
    repo = None
    try:
        repo = Repo(path, search_parent_directories=search_parent_directories)
        yield repo
    finally:
        if repo is not None:
            with suppress(Exception):
                repo.close()
```

GitPython's `Repo` accumulates open file handles. The context manager pattern guarantees cleanup. This is directly adoptable for any GitPython usage in Demarch Go/Python codebases that shell out via GitPython.

---

## Anti-Patterns to Avoid

### 1. Single-file servers that grow without bound

`app.py` at 11k lines demonstrates what happens when a FastMCP server is built as a single module: everything accretes to it. Establish module boundaries early. The natural split for MCP servers is: errors → instrument → helpers → tools (by cluster) → resources.

### 2. Cross-cutting parameters on every tool signature

The `format` parameter pattern (Finding 2) shows how a reasonable progressive enhancement — server-side output formatting — becomes an API surface pollution problem when bolted onto every tool. Cross-cutting concerns belong in middleware or transport, not function signatures.

### 3. Silent except-and-continue in business logic

The 122 bare `except Exception:` blocks (Finding 3) are a maintenance hazard. The pattern is acceptable for infrastructure fallbacks (logging, git metadata) but should never be used in business logic paths without at minimum a `logger.debug("...", exc_info=True)`.

### 4. String union types without Literal or Enum

String fields like `attachments_policy: str = "auto"` with inline comments `# "auto" | "inline" | "file"` are valid for models but unenforceable by the type system. Use `Literal` for configuration, `Enum` for model fields.
