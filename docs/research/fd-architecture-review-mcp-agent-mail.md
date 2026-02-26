# fd-architecture: mcp_agent_mail — Architecture Review

**Target:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/`
**Codebase:** Python / FastMCP coordination server, ~29k lines across 14 files
**Purpose of review:** Identify adoption-worthy patterns and structural anti-patterns
relevant to Demarch's coordination stack (Intermute, Interlock, Intercore — all Go).

---

## File Size Distribution

| File | Lines | Role |
|------|-------|------|
| `app.py` | 11,382 | All 47 MCP tool + resource registrations, all query helpers, output formatting, file reservation logic, macro implementations |
| `cli.py` | 4,738 | HTTP server, CLI entrypoints, viewer serving |
| `share.py` | 2,217 | Export / static bundle generation |
| `storage.py` | 3,236 | Git archive, commit queue, file locks, repo cache, attachment processing |
| `http.py` | 3,608 | HTTP transport, JWT auth, rate limiting, RBAC, SSE |
| `db.py` | 834 | Async engine, circuit breaker, schema, FTS setup |
| `models.py` | 210 | SQLModel table definitions (10 tables) |
| `config.py` | 486 | Typed settings (8 setting groups, ~40 knobs) |
| `guard.py` | 716 | Pre-commit hook install/uninstall |
| `llm.py` | 256 | LiteLLM thin wrapper |
| `rich_logger.py` | 975 | Rich console logging |
| `utils.py` | 233 | Slug, name generation, validation helpers |

---

## 1. Boundary and Coupling Analysis

### 1.1 Dependency Direction — Sound

The dependency graph is clean in direction:

```
models.py         (no upward imports)
    ↓
config.py         (no domain imports)
    ↓
db.py             (imports config, models)
    ↓
storage.py        (imports config, utils; NOT db directly — uses its own git/file I/O)
    ↓
app.py            (imports all of the above + llm, guard, utils, rich_logger)
    ↓
cli.py / http.py  (delivery layer — imports app, config)
```

Core domain (models, config) has no upward dependencies. Data access (db) does not import storage or app. Delivery (cli, http) does not bleed into domain. This is correct.

**Assessment: dependency direction is sound. Worth preserving this structure.**

### 1.2 `app.py` Monolith — Primary Structural Problem

At 11,382 lines, `app.py` performs six distinct roles simultaneously:

1. **MCP application factory** (`build_mcp_server` / `create_mcp_app` at the bottom)
2. **All 47 tool and ~15 resource handler registrations** (each defined as a nested function inside the factory)
3. **All query helper functions** (`_ensure_project`, `_get_project_by_identifier`, `_get_agent`, `_list_inbox`, `_create_message`, `_expire_stale_file_reservations`, etc. — ~30 functions)
4. **All output formatting machinery** (`_resolve_output_format`, `_encode_payload_to_toon_sync`, `_run_toon_encode`, `_apply_tool_output_format`, etc.)
5. **All project identity / slug computation logic** (`_compute_project_slug`, `_resolve_project_identity`, ~250 lines of git-remote parsing)
6. **All file reservation conflict detection** (`_file_reservations_conflict`, `_build_reservation_union_spec`, `_normalize_pathspec_pattern`, etc.)

All tool handlers are **nested functions inside `build_mcp_server`**, which means they close over `settings` and `mcp` — preventing extraction to separate files without significant refactoring. This was likely an intentional early-stage decision to keep access to `mcp.tool()` and `settings` without threading, but it has created a 11k-line nested scope.

**Must-fix boundary violation:** The conflict detection logic (file reservation intersection with pathspec) is conceptually the same responsibility as storage coordination, yet it lives in `app.py` instead of alongside file reservation data access. The ~250-line project identity resolution (`_resolve_project_identity`) is pure utility but also lives in `app.py`.

**Impact on Demarch:** Interlock (Go) already separates these layers correctly: protocol handling (MCP), business logic (coordination), data access (SQLite). The app.py pattern should not be replicated.

### 1.3 `storage.py` — Mostly Sound, One Concern

`storage.py` correctly owns:
- Git commit queue (`_CommitQueue`) with batching and conflict detection
- `AsyncFileLock` with metadata tracking and stale lock cleanup
- `_LRURepoCache` for GitPython Repo objects with FD-aware eviction
- Archive directory initialization (`ensure_archive`)
- File write operations (`write_message_bundle`, `write_agent_profile`, `write_file_reservation_records`)

One concern: `storage.py` imports `utils.validate_thread_id_format`, which is a validation call. Validation should be above storage in the call chain, not inside it. This is minor but worth noting as a pattern — validate at the entry point, not in the I/O layer.

### 1.4 `db.py` — Correctly Scoped

`db.py` owns only SQLAlchemy engine lifecycle, session management, query tracking hooks, circuit breaker state, and schema initialization. It has no tool logic or business rules. This is a clean separation worth adopting.

### 1.5 Cross-Layer Shortcuts

**Identified bypass (non-trivial):** The macro tools (`macro_start_session`, `macro_prepare_thread`, `macro_contact_handshake`, `macro_file_reservation_cycle`) call other tools via the FastMCP tool registry:

```python
mcp_with_tools = cast(_FastMCPToolGetter, mcp)
_file_reservation_tool = cast(FunctionTool, await mcp_with_tools.get_tool("file_reservation_paths"))
_file_reservation_run = await _file_reservation_tool.run({...})
```

This is a tool calling another tool via the MCP registry (not calling the underlying query helper directly). It means macro implementations depend on the MCP framework being fully initialized and on tool names being stable. If a tool is renamed or filtered out, macros silently fail. The alternative — calling the shared query helper directly — would be cleaner and not framework-coupled.

---

## 2. Pattern Analysis

### 2.1 Good: `@_instrument_tool` Decorator Pattern

The `_instrument_tool` decorator is a strong pattern. It provides:
- Metrics tracking (call count, error count per tool)
- Capability enforcement (`_enforce_capabilities`)
- Logging integration (start/end via `rich_logger`)
- Query tracking (slow query detection via `db.py` context vars)
- EMFILE retry on safe idempotent tools
- Unified error wrapping (9 exception types mapped to structured `ToolExecutionError`)

This is applied consistently with two stacked decorators:
```python
@mcp.tool(name="health_check", ...)
@_instrument_tool("health_check", cluster=CLUSTER_SETUP, ...)
async def health_check(...):
```

**Worth adopting in Demarch:** Interlock and Intermute tools each handle errors independently. A unified `@instrument_tool` decorator wrapping MCP handlers that centralizes metrics, error classification, and logging would reduce the per-tool boilerplate in Go by building a shared middleware chain.

### 2.2 Good: Tool Clustering and Filtering

Tools are assigned to named clusters (`CLUSTER_MESSAGING`, `CLUSTER_FILE_RESERVATIONS`, `CLUSTER_MACROS`, etc.). The `_should_expose_tool` function filters the entire tool surface at startup based on config profiles (`full`, `core`, `minimal`, `messaging`, `custom`). This reduces MCP context by up to ~70% for minimal workflows.

This pattern is applicable to Interlock's tool surface as it grows. Exposing fewer tools in constrained contexts is a legitimate cost-reduction strategy for multi-agent coordination.

**Worth adopting:** Tool clusters with startup-time filtering profiles.

### 2.3 Good: Structured Error Responses with `ToolExecutionError`

```python
class ToolExecutionError(Exception):
    def __init__(self, error_type: str, message: str, *, recoverable: bool = True, data: Optional[dict] = None):
```

Every error carries: typed error code, user-readable message, recoverability flag, and structured data for programmatic handling. This lets calling agents distinguish retryable from fatal failures without parsing strings.

**Demarch relevance:** Intercore and Intermute currently return plain errors. Adopting a structured error envelope with `recoverable` classification would improve agent decision-making.

### 2.4 Good: Circuit Breaker on DB Layer

`db.py` implements a proper circuit breaker:
- Tracks consecutive failures
- Opens circuit after 5 failures, blocking new operations for 30s
- Half-open state after reset window for recovery testing
- `@retry_on_db_lock` decorator with exponential backoff + ±25% jitter

This is appropriate for a shared SQLite database under multi-agent concurrent load. The jitter prevents thundering herd on reconnection.

**Demarch note:** Interlock and Intermute already use SQLite. This circuit breaker pattern (failure threshold, timed reset, half-open probe) is worth porting to the Go coordination stack. The current Demarch SQLite handling (see MEMORY.md: `MaxOpenConns(1)`, WAL mode, 5s busy timeout) covers the basics but lacks circuit breaker protection for sustained contention.

### 2.5 Good: Commit Queue with Batching

`storage.py`'s `_CommitQueue`:
- Batches non-conflicting commits from multiple concurrent agents into a single git operation
- Detects path conflicts — overlapping paths are processed sequentially, non-overlapping are merged
- Falls back to direct commit when queue is full or processor is stopped
- Background asyncio task with configurable max_wait_ms and max_batch_size

This is a genuine architectural contribution to the multi-agent git-coordination problem. The key insight: git commits are serialized by the index lock, but many agents write to different subdirectories. Batching them reduces lock acquisition frequency proportionally to the batch ratio.

**Demarch note:** Interlock uses file locks for coordination but does not batch git commits. If Interlock adds git-backed audit trails, this pattern is directly applicable.

### 2.6 Good: AsyncFileLock with Stale Lock Detection

`AsyncFileLock` in `storage.py` combines:
- `SoftFileLock` (cross-platform)
- Metadata file (`*.owner.json`) recording PID and creation timestamp
- Stale detection: lock is stale if owner process is dead OR age exceeds `stale_timeout_seconds`
- Process-level `asyncio.Lock` preventing re-entrant acquisition within the same process
- Adaptive timeout: 10% of total on first attempt, exponential growth, full remainder on last attempt

The metadata file pattern solves the classic lock problem: without owner tracking, you cannot distinguish a live lock from a crashed process. This is a correct design.

**Demarch note:** Interlock's file reservation system tracks ownership in SQLite, not in lock files. The lock metadata file as a sidecar (`.archive.lock` + `.archive.lock.owner.json`) is a simpler approach that works without a database connection during lock acquisition.

### 2.7 Anti-Pattern: Inline Rich Logging Repeated Per Tool

Many tools repeat this pattern inline inside the tool body:

```python
if get_settings().tools_log_enabled:
    try:
        import importlib as _imp
        _rc = _imp.import_module("rich.console")
        _rp = _imp.import_module("rich.panel")
        Console = _rc.Console
        Panel = _rp.Panel
        Console().print(Panel.fit(f"project={project_key}\n...", title="tool: mark_message_read", ...))
    except Exception:
        pass
```

This block appears in at least 5 tools (`mark_message_read`, `acknowledge_message`, `register_agent`, and others). It should be in `_instrument_tool` — that decorator already has `log_ctx` and `rich_logger` integration. The per-tool repetition is pure duplication and should have been eliminated when `_instrument_tool` was built.

**Classification:** Accidental complexity. The decorator handles 95% of this; the remaining 5% adds noise.

### 2.8 Anti-Pattern: `_resolve_project_identity` — 300-Line God Function

`_resolve_project_identity` (lines ~1836–2085) is a 250-line function that does:
1. Git repo open and traversal
2. Remote URL parsing (two separate normalization implementations — one at module level `_norm_remote`, one as a nested function inside this function)
3. Discovery YAML parsing (also nested inside this function)
4. Project UID derivation via 6-step precedence chain
5. Private marker file write
6. Rich console logging

The duplication of `_norm_remote` is the most direct symptom: there is a module-level `_norm_remote` at line ~1739 (inside `_compute_project_slug`) and another nested `_norm_remote` inside `_resolve_project_identity`. They implement the same URL normalization with slight differences, and neither calls the other.

**Boundary violation:** Identity resolution logic belongs in a dedicated `identity.py` module, not embedded in the application factory file.

### 2.9 Anti-Pattern: Feature Flags Creating Parallel Architecture

Several product-level tools are gated behind `if settings.worktrees_enabled:`:

```python
if settings.worktrees_enabled:
    @_instrument_tool("ensure_product", ...)
    async def ensure_product(...):
        # real implementation
    ...
else:
    async def ensure_product(...):
        raise ToolExecutionError("FEATURE_DISABLED", "Product Bus is disabled.")
```

This means:
- The factory contains two code paths for 6+ tools
- `build_mcp_server` has conditional blocks interspersed with tool definitions
- Reading the tool set requires tracking flag state through 600+ lines of factory code

This is a hidden parallel architecture. The "disabled" stubs are no-ops that masquerade as real tools. When `worktrees_enabled=False`, those tools appear registered but immediately error — a worse user experience than not exposing them at all, and the same filtering mechanism (`_should_expose_tool`) already exists to handle this case cleanly.

**Recommendation for Demarch:** Use the cluster/profile filtering mechanism at registration time rather than injecting disabled stubs into the factory body.

### 2.10 Anti-Pattern: `_get_project_by_identifier` Mixes Concerns

At ~100 lines, `_get_project_by_identifier` does:
1. Input validation and placeholder detection
2. Path canonicalization (symlink resolution)
3. DB lookup by slug
4. Fallback: DB lookup by human_key
5. Fuzzy matching with suggestions if not found
6. Error construction with human-readable alternatives

The fuzzy matching + suggestion generation runs a full table scan on every not-found lookup. For small deployments this is acceptable, but the concern is that lookup helpers are loading business logic (similarity scoring) into what should be a simple data access function. The `_find_similar_projects` call performs string distance computation over every project in the DB — this should be a last-resort path with explicit rate limiting, not an automatic fallback.

---

## 3. Simplicity and YAGNI Analysis

### 3.1 Output Format System — Necessary Complexity

The TOON output format system (`_encode_payload_to_toon_sync`, `_run_toon_encode`, `_looks_like_toon_rust_encoder`, etc.) is ~200 lines. The purpose is token compression for LLM context. This is genuine domain complexity — agents consuming MCP tool results benefit from compact representations. The encoder validation (`_looks_like_toon_rust_encoder`) guarding against the Node.js `toon` CLI is a safety check grounded in a real failure mode.

**Assessment: required complexity given the use case.**

### 3.2 `_LRURepoCache` — Justified

A custom LRU cache for GitPython `Repo` objects exists because:
- GitPython Repo objects hold open file descriptors
- Naive caching causes FD exhaustion under multi-agent load
- Python's `sys.getrefcount()` heuristic for eviction was proven unreliable (phantom refs from stack frames)
- Time-based eviction (60s grace period post-eviction) is the correct approach

The implementation is well-commented with the rationale. This is domain-required complexity.

**Assessment: required. The comment explaining why `sys.getrefcount()` was abandoned is exactly the kind of institutional knowledge that belongs in MEMORY.md.**

### 3.3 `_CommitQueue` — Justified but Premature for Most Deployments

The commit queue batching implementation (~200 lines) is valuable under high concurrency. However, it activates for all deployments regardless of load. The max_batch_size=10 and max_wait_ms=50 defaults mean every git operation waits up to 50ms for potential batching even when there is only one agent writing.

**Assessment: the design is correct but the batch wait adds latency in single-agent scenarios. A simpler fast path (skip the queue when queue is empty and no pending requests) would reduce this cost without losing the batching benefit under load.**

### 3.4 `_validate_iso_timestamp` / `_parse_iso` — Redundancy

Two ISO timestamp parsers exist: `_parse_iso` (silent failure, returns None) and `_validate_iso_timestamp` (raises `ToolExecutionError` on failure). The `_validate_iso_timestamp` function duplicates the parsing logic of `_parse_iso` instead of calling it. This is minor but symptomatic — shared parsing utilities in `utils.py` would be cleaner.

### 3.5 Macro Tools — Appropriate Abstraction

The macro tools (`macro_start_session`, `macro_prepare_thread`, `macro_contact_handshake`, `macro_file_reservation_cycle`) compose lower-level operations into common startup sequences. These have real callers (agent workflows that need to bootstrap quickly) and reduce the number of round-trips from 4-6 to 1. The abstraction is justified.

The implementation flaw (calling via MCP tool registry instead of shared query helpers) is addressed in section 2.5 above — the abstraction is correct, the implementation coupling is wrong.

### 3.6 `share.py` — Questionable Boundary

`share.py` implements a full static bundle exporter with: ZIP archive generation, secret pattern scrubbing, agent pseudonymization, base64 attachment embedding, chunked export for large archives, and viewer asset embedding. At 2,217 lines it is larger than `db.py` + `models.py` + `config.py` combined.

This functionality is entirely separate from the coordination protocol. It uses `sqlite3` directly (bypassing the async SQLAlchemy layer) and reads raw files. It is effectively a standalone export tool bundled into the same package.

**Assessment:** `share.py` should be a separate CLI tool or subpackage. Its inclusion in the main package creates an unnecessary dependency surface and complicates testing. This is scope creep from the core coordination responsibility.

---

## 4. Dependency Structure Summary

```
models.py ← no deps within package
config.py ← no deps within package
utils.py  ← no deps within package
llm.py    ← config
db.py     ← config, models
guard.py  ← config (minimal)
storage.py ← config, utils (NOT db — uses its own I/O)
rich_logger.py ← config (minimal)
app.py    ← ALL of the above
http.py   ← app, config
cli.py    ← app, http, config, share
share.py  ← config (bypasses db/storage entirely, uses raw sqlite3)
```

Correct observation: `storage.py` does NOT import `db.py`. This means the file system archive (git-backed persistence) and the database persistence (SQLAlchemy/SQLite) are independent layers. This is architecturally sound — they have different failure modes and locking strategies.

Incorrect observation: `share.py` imports `config` but bypasses the async db session layer entirely, using raw `sqlite3` synchronously. This is intentional for export use (reads are safe without WAL concerns) but means `share.py` has knowledge of the raw DB schema that is not mediated by models.

---

## 5. Findings for Demarch Coordination Stack

### Adopt

1. **`@instrument_tool` middleware pattern** — centralize metrics, error wrapping, capability checks, and logging in a single decorator rather than per-handler boilerplate. Applicable to Interlock's MCP tool surface.

2. **Structured error envelope with recoverability flag** — `ToolExecutionError(error_type, message, recoverable=True, data={})`. Intercore and Intermute error responses are untyped. This pattern improves agent retry logic.

3. **Circuit breaker on DB layer** — 5-failure threshold, 30s open window, half-open probe. The Go Demarch stack uses SQLite + WAL mode correctly but lacks circuit breaker protection for sustained contention.

4. **Tool cluster definitions with startup-time filtering** — named clusters + profile-based tool exposure. As Interlock's tool count grows, context budget management matters.

5. **Commit queue with path-conflict batching** — if Interlock adds git-backed audit trails, batch non-conflicting writes. The asyncio.Future-per-request pattern for backpressure is clean.

6. **`AsyncFileLock` with owner metadata sidecar** — the `.lock` + `.lock.owner.json` pattern enables stale lock detection without a database. The time-based eviction (not refcount-based) is the correct approach.

7. **LRU repo cache with grace-period eviction** — if Demarch ever holds GitPython objects open (currently not the case), the time-based cleanup is significantly more reliable than reference counting.

8. **Tool directory resource** (`resource://tooling/directory`) — exposing a machine-readable tool directory clustered by workflow reduces agent orientation overhead. This is a low-cost addition to Interlock.

### Avoid

1. **Nested tool registrations inside factory function** — all 47 tools are closures inside `build_mcp_server`. This prevents module-level tool extraction. Define tools at module level with an explicit settings parameter, or use a class-based approach.

2. **Feature flags creating parallel architecture** — disabled tool stubs inline with real implementations. Use the filtering/profile mechanism at registration time. Never define two versions of the same tool in the same factory body.

3. **`share.py`-style scope creep** — bundle export is a separate concern from the coordination protocol. Keep the core package focused; move export to a standalone CLI subpackage.

4. **Inline macro-to-tool calls via framework registry** — macros calling `mcp.get_tool(...).run(...)` couples macro implementations to MCP framework internals and tool name stability. Call shared query helpers directly.

5. **Repeated inline logging blocks per tool** — if a decorator already handles instrumentation, do not add per-tool logging blocks. The decorator should be the single enforcement point.

6. **Fuzzy project lookup on every not-found** — running similarity scoring over all projects on each failed lookup is a latency trap as project count grows. Make fuzzy matching an explicit opt-in debug path.

---

## 6. Architecture Verdict

The codebase demonstrates strong infrastructure discipline (db.py, storage.py, async patterns) and a well-designed tool instrumentation layer. The dependency direction is correct. The SQLite concurrency handling (WAL, circuit breaker, commit queue) is production-grade.

The primary structural problem is `app.py`'s role as an everything-monolith: it combines tool registration, business logic, query helpers, output formatting, project identity resolution, file reservation conflict detection, and application factory into a single 11k-line file. This is the consequence of using nested closures for tool registration — once every tool closes over `mcp` and `settings`, extraction becomes non-trivial.

For Demarch's Go coordination stack, the correct structure is already present: Interlock has separate handler, business logic, and data access layers. The patterns worth importing are the instrumentation middleware, structured error envelope, circuit breaker, and tool cluster filtering — all of which are framework-agnostic.

The most common failure mode in this codebase is duplication within the same file: two `_norm_remote` implementations, two ISO timestamp parsers, inline logging blocks repeated across tools, and disabled tool stubs duplicating real tool signatures. These are all symptoms of a monolith that has outgrown its single-file structure.

---

*Reviewed by: fd-architecture (flux-drive review agent)*
*Date: 2026-02-24*
*Source: `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/`*
