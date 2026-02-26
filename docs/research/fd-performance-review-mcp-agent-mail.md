# flux-drive Performance Review: mcp_agent_mail

**Target:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/`
**Scope:** SQLite query patterns, connection pool, Git I/O, commit queue, memory, FTS5, async patterns, scaling limits
**Purpose:** Identify performance patterns worth adopting and bottlenecks to avoid when building Demarch's Go-based coordination services

---

## Performance Profile Summary

This is a Python/FastMCP server using async SQLAlchemy (aiosqlite) with SQLite WAL mode, GitPython for dual-persistence, and a commit queue for batching Git writes. The server is designed for a multi-agent coordination workload: many concurrent agents sending and receiving messages, with each operation touching both SQLite (authoritative) and a Git repository (audit archive).

The dominant latency costs are:
1. Git commits on every message send (blocking thread dispatch, lock contention)
2. `func.lower()` comparisons on un-indexed columns disabling index use
3. The `_find_similar_*` error-path full table scans reaching the hot path
4. Per-call `await ensure_schema()` in 48 places causing unnecessary lock acquisitions

---

## Finding 1: Connection Pool of 50 for SQLite is Architecturally Unsound

**Severity: must-fix for any Go port, diagnostic for the Python implementation**

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/db.py` lines 391-393

```python
pool_size = settings.pool_size if settings.pool_size is not None else (50 if is_sqlite else 25)
max_overflow = settings.max_overflow if settings.max_overflow is not None else (4 if is_sqlite else 25)
```

SQLite is a **single-writer database**. At any given moment, exactly one writer can hold the write lock; all others queue behind SQLite's internal `busy_timeout` mechanism. Having 50 connections in the pool for a single-writer database creates 50 threads that can independently acquire connections from the pool, then all serialize at the SQLite write lock anyway.

The actual write throughput ceiling is set by SQLite's WAL writer concurrency (1), not by pool size. A pool of 5-10 connections for SQLite would service concurrent readers fine and would not change write throughput at all. The current 50-connection pool wastes memory (each SQLAlchemy connection object carries overhead), increases the surface area for pool-exhaustion scenarios, and inflates file descriptor consumption alongside the Git repo cache.

The comment in the code ("Higher default pool size for bursty multi-agent workloads") suggests this was configured to solve write queueing, but pool size does not help write contention — that is solved by WAL mode (already enabled) and the commit queue. The right approach is a small pool with a longer `pool_timeout`.

**Go port implication:** Go's `database/sql` pool for SQLite (using `modernc.org/sqlite` or `mattn/go-sqlite3`) should be configured with `MaxOpenConns(1)` for write connections and a separate read pool if needed, mirroring the Autarch pattern already used in this monorepo (`pkg/db`).

---

## Finding 2: `func.lower()` on `topic` Column Disables Index on Hot Read Paths

**Severity: must-fix**

**Files:**
- `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/app.py` line 3907
- `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/app.py` line 7131

```python
# In _list_inbox (called by fetch_inbox, macro_prepare_thread, fetch_summary, etc.):
stmt = stmt.where(cast(Any, func.lower(Message.topic)) == topic.lower())

# In fetch_topic:
cast(Any, func.lower(Message.topic)) == topic_name.strip().lower(),
```

The `messages` table has `idx_messages_project_topic` on `(project_id, topic)`. Wrapping `Message.topic` in `func.lower()` means SQLite evaluates the expression against every row in the project's message set — it cannot use the composite index. The index is defined on the raw column value, not a lowercased expression.

The model (`models.py` line 94) defines the index as `Index("idx_messages_project_topic", "project_id", "topic")`, but queries apply `lower()` to the column, producing a full scan filtered by project_id at best.

**Fix:** Enforce topic storage in lowercase at insert time (already constrained to `[A-Za-z0-9_-]+` by validation) and compare without wrapping. Alternatively, create an expression index: `CREATE INDEX idx_messages_project_topic_lower ON messages(project_id, lower(topic))`. The simpler fix is to lowercase at write time since the validation regex would produce identical results.

**Scale impact:** At 1,000 messages per project, this is a scan of 1,000 rows per `fetch_inbox` call with a topic filter. At 10,000 messages it becomes meaningful latency for agents that poll frequently.

---

## Finding 3: `_find_similar_*` Full Table Scans on the Error Path That Reaches the Hot Path

**Severity: must-fix**

**Files:**
- `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/app.py` lines 2158-2173 (`_find_similar_projects`)
- `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/app.py` lines 2176-2189 (`_find_similar_agents`)

```python
async def _find_similar_projects(identifier: str, limit: int = 5, min_score: float = 0.4):
    async with get_session() as session:
        result = await session.execute(select(Project))  # Full table scan
        projects = result.scalars().all()
        for p in projects:
            slug_score = _similarity_score(slug, p.slug)          # SequenceMatcher per row
            key_score = _similarity_score(identifier, p.human_key)  # SequenceMatcher per row

async def _find_similar_agents(project: Project, name: str, limit: int = 5, min_score: float = 0.4):
    async with get_session() as session:
        result = await session.execute(
            select(Agent).where(cast(Any, Agent.project_id == project.id))  # All agents in project
        )
        agents = result.scalars().all()
        for a in agents:
            score = _similarity_score(name, a.name)  # SequenceMatcher per row
```

`SequenceMatcher` has O(n*m) complexity per comparison. With 50 agents per project and a 10-character name, this is manageable, but it is called on every failed `_get_agent` call.

The critical issue is that `_get_agent` is called on every `send_message`, `fetch_inbox`, and virtually every other tool. If an agent name is misspelled or a configuration issue causes a bad name to be passed (which the code's extensive placeholder detection suggests is common), the error path triggers a full scan of all agents in the project with O(n) SequenceMatcher calls.

`_find_similar_projects` scans the entire `projects` table — an even larger concern as deployments grow.

**Go port implication:** Do not inline fuzzy matching into lookup helpers. Gate similarity search behind explicit user-facing hint endpoints, or impose a hard row limit (e.g., `LIMIT 100`) before loading into application memory for comparison.

---

## Finding 4: `_get_agent` Uses `func.lower()` on a Non-Expression-Indexed Column

**Severity: must-fix**

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/app.py` lines 3197-3199

```python
result = await session.execute(
    select(Agent).where(Agent.project_id == project.id, func.lower(Agent.name) == name.lower())
)
```

`agents` has `UniqueConstraint("project_id", "name")` and `Field(index=True)` on `name`, but querying via `lower(name)` bypasses this index. Every agent lookup performs a filtered scan rather than an index seek.

`_get_agent` is called on the critical path of `send_message`, `fetch_inbox`, `acknowledge_message`, and many other tools. At 100 agents per project this is a 100-row scan per tool call.

The same pattern appears in `_agent_name_exists` (line 2834) and in `register_agent` (lines 3072-3076).

**Fix:** Normalize agent names to a canonical case at registration and store/compare consistently. The existing `validate_agent_name_format` function requires PascalCase already; if that invariant is enforced, case-insensitive comparison is unnecessary. If case folding is required, create an expression index `CREATE INDEX idx_agents_project_name_lower ON agents(project_id, lower(name))`.

---

## Finding 5: 48 `await ensure_schema()` Call Sites — Unnecessary Lock Acquisition per Tool Call

**Severity: moderate**

**File:** `app.py` — 48 occurrences of `await ensure_schema()`

```python
# db.py:
async def ensure_schema(...) -> None:
    global _schema_ready, _schema_lock
    if _schema_ready:
        return                     # Fast path: module-level bool check
    if _schema_lock is None:
        _schema_lock = asyncio.Lock()
    async with _schema_lock:      # Lock acquisition even on fast path
```

After the schema is initialized, `_schema_ready` is `True` and `ensure_schema` returns immediately. The check is a module-level boolean, so the fast path is a single Python attribute lookup with no lock acquisition — this is acceptably cheap.

However, the pattern of calling `ensure_schema()` inside `_get_agent()` and `_get_project_by_identifier()` means that each composed tool (e.g., `send_message` which calls both) runs `ensure_schema()` multiple times per request. The overhead is negligible after warmup, but it is a code smell that makes the dependency on initialization order unclear.

**Go port implication:** Initialize schema once at startup before the server accepts connections. Never check initialization inside request handlers.

---

## Finding 6: Git I/O on the Critical Write Path — Synchronous Overhead Even With Thread Offload

**Severity: must-fix for latency, worth adopting the mitigation pattern**

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/storage.py` lines 1208-1317

Every `send_message` call triggers:
1. File creation: 1 canonical `.md` + 1 outbox copy + N inbox copies (one per recipient), each via `await _to_thread(_write_text, ...)` which dispatches to `asyncio.to_thread`
2. Directory creation: `canonical_dir.mkdir`, `outbox_dir.mkdir`, N `inbox_dir.mkdir` calls — each a separate `asyncio.to_thread` dispatch
3. Optional thread digest: an additional file read + append + lock acquisition
4. A git commit: `repo.index.add(rel_paths)` + `repo.index.commit(...)` — all synchronous GitPython calls offloaded to a thread

For a message with 3 recipients, that is approximately 7-9 separate `asyncio.to_thread` dispatches for file operations, plus 1 thread dispatch for the git commit itself. Each thread dispatch carries Python thread-pool overhead and a context switch.

The `_commit_direct` function (lines 1735-1892) opens a fresh `Repo(str(repo_root))` on every call, despite the commit queue batching existing to reduce this. The repo object is not taken from the LRU cache; it is always created fresh and closed in `finally`. This means every batched commit that falls through to `_commit_direct` pays the cost of GitPython's `Repo.__init__`, which reads the git config, HEAD, and index.

The FTS5 trigger fires on every insert, adding an FTS index write to each `send_message` database transaction.

**Latency estimate:** A `send_message` call with 2 recipients takes approximately:
- 2-3ms SQLite write (WAL, well-indexed)
- 5-10ms for 6-8 file writes (SSD, `asyncio.to_thread` dispatch overhead)
- 15-50ms for the git commit (GitPython Repo init, index.add, index.commit)
- Total: 25-65ms per message in the common case

The commit queue's 50ms `max_wait` means a caller blocks for up to 50ms waiting for batching before their commit executes. For single messages (the common case), this adds 50ms of latency for zero benefit — the batch size will be 1 after the wait.

**Patterns worth adopting:**
- `asyncio.to_thread` wrapping for all blocking Git/filesystem operations (correct)
- Commit queue concept for batching (correct, but the parameters need tuning)
- LRU repo cache to amortize `Repo.__init__` cost (correct, but not used by `_commit_direct`)

---

## Finding 7: Commit Queue Tuning Is Wrong for Single-Agent Scenarios

**Severity: moderate**

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/storage.py` lines 84-303

```python
class _CommitQueue:
    def __init__(
        self,
        max_batch_size: int = 10,
        max_wait_ms: float = 50.0,   # <-- the problem
        max_queue_size: int = 100,
    ) -> None:
```

The process loop:
```python
first = await asyncio.wait_for(self._queue.get(), timeout=self._max_wait_ms / 1000.0)
# then:
deadline = time.monotonic() + (self._max_wait_ms / 1000.0)
while len(batch) < self._max_batch_size and time.monotonic() < deadline:
```

Every enqueued commit waits up to 50ms for batching to occur. In a single-agent scenario (one agent sending messages sequentially), each `send_message` call pays 50ms of commit latency that buys nothing — the next commit arrives after the current one has already been processed.

The batching benefit only materializes when multiple agents send messages concurrently to the same repository within the 50ms window. For a typical 1-5 agent deployment, the queue adds latency without reducing commit count.

Additionally, `_process_batch` only merges batches of up to 5 requests (line 266: `if can_batch and len(requests) <= 5`), which is more conservative than the queue's `max_batch_size=10`. The batch size tracking (`_batch_sizes`) uses `list.pop(0)` for a rolling window, which is O(n) and should use `collections.deque(maxlen=100)`.

**Fix recommendation:** Set `max_wait_ms=5` for typical deployments. The current 50ms is tuned for a dense concurrent scenario that is unlikely in practice. Alternatively, implement a triggered-flush model: process immediately when the queue is non-empty and the processor is idle, with a small window only if a second item arrives within 5ms.

---

## Finding 8: The `_order.pop(0)` and `_batch_sizes.pop(0)` O(n) List Operations in Hot Paths

**Severity: low-moderate**

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/storage.py`

```python
# _LRURepoCache (line 430):
oldest_key = self._order.pop(0)   # O(n) list shift

# _CommitQueue (line 291):
self._batch_sizes.pop(0)           # O(n) list shift
```

The LRU order tracking uses a plain Python `list` with `pop(0)` (O(n) shift) and `list.remove(key)` (O(n) scan) on every cache access. With `maxsize=16`, this is bounded to 16-element operations — negligible in absolute terms but wrong in principle. The same pattern for `_batch_sizes` (rolling window of 100) is similarly bounded but could be `collections.deque(maxlen=100)` for zero-allocation behavior.

The `_order.remove(key)` call on every cache hit (line 401) is also O(n):
```python
with contextlib.suppress(ValueError):
    self._order.remove(key)
self._order.append(key)
```

**Fix:** Use `collections.OrderedDict` for the LRU cache (move-to-end is O(1)) and `collections.deque(maxlen=100)` for the rolling window. Neither fix changes behavior; both eliminate the list-shifting overhead.

**Go port implication:** Use a linked-list-based LRU or `container/list` + map for O(1) LRU operations.

---

## Finding 9: Passive WAL Checkpoint on Every Connection Checkin Adds Write Lock Pressure

**Severity: moderate**

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/db.py` lines 460-478

```python
@event.listens_for(engine.sync_engine, "checkin")
def on_checkin(dbapi_conn: Any, connection_record: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA wal_checkpoint(PASSIVE)")
```

`PRAGMA wal_checkpoint(PASSIVE)` runs on every connection return to pool. With a pool of 50 connections and bursty traffic, this fires 50 times per burst even when the WAL is small. PASSIVE mode doesn't block readers or writers, but it does consume CPU and disk bandwidth. More importantly, it prevents the WAL from being checkpointed in a controlled manner and can interact poorly with the `wal_autocheckpoint=1000` setting by fragmenting checkpoints across many small operations.

A better approach: checkpoint from a dedicated background task on a fixed interval (e.g., every 30 seconds) using `PRAGMA wal_checkpoint(RESTART)` when the server is otherwise idle. The SQLite WAL autocheckpoint at 1000 pages is already a reasonable backstop.

**Go port implication:** Run checkpoints from a background goroutine triggered by WAL size crossing a threshold, not on every connection return.

---

## Finding 10: `_list_inbox` Missing Composite Index for the MessageRecipient Join

**Severity: moderate**

**Files:**
- `app.py` lines 3889-3896 (`_list_inbox`)
- `db.py` lines 756-762 (`idx_message_recipients_agent_message`)
- `models.py` lines 79-83

```python
# The query:
stmt = (
    select(Message, MessageRecipient.kind, sender_alias.name)
    .join(MessageRecipient, MessageRecipient.message_id == Message.id)
    .join(sender_alias, cast(Any, Message.sender_id == sender_alias.id))
    .where(
        cast(Any, Message.project_id) == project.id,
        MessageRecipient.agent_id == agent.id,
    )
    .order_by(desc(Message.created_ts))
    .limit(limit)
)
```

The existing indexes:
- `idx_message_recipients_agent_message` on `(agent_id, message_id)` — good for the join condition
- `idx_messages_project_created` on `(project_id, created_ts)` — good for ordering within project
- `idx_messages_project_sender_created` on `(project_id, sender_id, created_ts DESC)` — covers outbox pattern

The `_list_inbox` query joins `message_recipients` on `agent_id` (indexed) then filters `messages.project_id` and orders by `messages.created_ts`. The SQLite query planner will likely use `idx_message_recipients_agent_message` to find message IDs for the agent, then do an ordered scan of `messages` to apply the `project_id` filter and `created_ts` ordering. This is adequate for typical agent counts but degrades as message volume grows.

A covering index `(agent_id, message_id)` exists (fine), but a composite `(agent_id, project_id)` index on `message_recipients` would allow the planner to filter by both agent and project before touching `messages` at all. This is the most impactful missing index for the read hot path.

**Recommended additional index:**
```sql
CREATE INDEX idx_message_recipients_agent_project
ON message_recipients(agent_id, message_id)
-- Note: project_id is not on message_recipients; the join is unavoidable
-- The real fix is to denormalize project_id onto message_recipients
```

Since `message_recipients` does not carry `project_id`, the most effective fix is to add `project_id` to `message_recipients` (denormalization), enabling a single-table seek for inbox queries. This is a schema change with migration implications, but it would reduce `_list_inbox` from a join query to a filtered index scan.

---

## Finding 11: `send_message` Thread-Participant Lookup Queries a Session After It Is Closed

**Severity: correctness + latency**

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/app.py` lines 5678-5695

```python
async with get_session() as s:
    stmt = (
        select(Message, sender_alias.name)
        ...
    )
    thread_rows = [(row[0], row[1]) for row in (await s.execute(stmt)).all()]

# Session `s` is now closed — context manager has exited
message_ids = [m.id for m, _ in thread_rows if m.id is not None]
if message_ids:
    recipient_rows = await s.execute(   # BUG: s is closed
        select(Agent.name)
        .join(MessageRecipient, ...)
        .where(cast(Any, MessageRecipient.message_id).in_(message_ids))
    )
```

After the `async with get_session() as s:` block exits, the session is closed. The subsequent `await s.execute(...)` on the closed session `s` will fail with a `DetachedInstanceError` or similar SQLAlchemy error. This means the recipient auto-allow logic for thread replies is broken in practice — the exception is silently swallowed by `except Exception: logger.exception(...)` at line 5697, so the auto-allow check for thread replies silently fails, potentially causing legitimate reply messages to be blocked.

This is a correctness bug that also has a latency implication: the thread-participant query was intended as an optimization to avoid contact enforcement for replies, but it silently never runs, meaning every reply to a thread goes through the full contact enforcement path unnecessarily.

---

## Finding 12: `_find_similar_projects` Loads All Projects Into Python Memory

**Severity: moderate, scaling concern**

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/app.py` lines 2162-2172

```python
result = await session.execute(select(Project))  # No LIMIT, no WHERE
projects = result.scalars().all()
```

There is no `LIMIT` on this query. As the number of projects grows, this loads the entire `projects` table into memory on every failed project lookup. At 1,000 projects each with a `human_key` of average 50 bytes, this is ~50KB per call — small but unbounded. At 10,000 projects it becomes a meaningful allocation and DB round-trip for what is an error reporting path.

The same issue exists in `_find_similar_agents` for the per-project agent table, though that is bounded by project size.

**Fix:** Add `LIMIT 200` to the similarity scan queries and accept that suggestions may be incomplete for large deployments.

---

## Finding 13: `RECENT_TOOL_USAGE` Deque Scan for Activity Feed Is O(n)

**Severity: low**

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/app.py` lines 10170-10174

```python
RECENT_TOOL_USAGE: deque[tuple[datetime, str, Optional[str], Optional[str]]] = deque(maxlen=4096)

# In activity_feed tool:
for ts, tool_name, proj, ag in list(RECENT_TOOL_USAGE):
    if ts < cutoff:
        continue
```

The deque is converted to a `list()` (allocating 4096 tuples) and then scanned linearly. The deque maintains insertion order (newest last), so the scan could use `reversed()` and break on first old entry. However, the deque is appended newest-last, so scanning from the end and breaking early would be more efficient.

With `maxlen=4096`, the worst case is 4096 tuple comparisons — this is O(1) in practical terms but allocates a list copy on every `activity_feed` call. Using `reversed(RECENT_TOOL_USAGE)` directly avoids the allocation and enables early exit.

---

## Finding 14: FTS5 Update Trigger Writes on Every Message Update

**Severity: low, design note**

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/db.py` lines 726-735

```sql
CREATE TRIGGER IF NOT EXISTS fts_messages_au
AFTER UPDATE ON messages
BEGIN
    DELETE FROM fts_messages WHERE rowid = old.id;
    INSERT INTO fts_messages(rowid, message_id, subject, body)
    VALUES (new.id, new.id, new.subject, new.body_md);
END;
```

Messages are immutable in the application design — once sent, they are not updated. The update trigger exists but should never fire. It has no performance impact, but it adds complexity and FTS maintenance overhead if messages were ever updated (e.g., during migration or admin operations). This is acceptable as-is.

The FTS5 insert trigger on `fts_messages_ai` fires on every `send_message` as part of the same write transaction. FTS5 tokenization and index update cost is proportional to body length. For large message bodies (agents can send up to several KB of Markdown), the FTS update adds measurable write latency. This is a necessary cost for the search feature.

---

## Finding 15: The `_PROCESS_LOCKS` Dict Grows Without Bound

**Severity: low, long-running process concern**

**File:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/storage.py` lines 355-356

```python
_PROCESS_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}
_PROCESS_LOCK_OWNERS: dict[tuple[int, str], int] = {}
```

Entries are added when `AsyncFileLock.__aenter__` acquires a process-level lock and removed when `__aexit__` runs. However, the cleanup logic only removes the lock if `not self._process_lock.locked()` after release. If an exception path doesn't properly clean up, entries accumulate.

In practice, the cleanup runs reliably in the `__aexit__` path. But `_PROCESS_LOCKS` grows to one entry per unique lock path ever acquired in the process lifetime. For a long-running server handling many unique commit lock paths (one per unique set of file paths), this dict could accumulate thousands of entries over days of operation. Each entry is a lightweight asyncio.Lock, so memory impact is small but not zero.

**Go port implication:** Use a `sync.Map` with explicit expiry or a fixed-size cache for process-level lock coordination.

---

## Patterns Worth Adopting in Demarch's Go Services

### Pattern A: Circuit Breaker for Database Operations

The circuit breaker in `db.py` (lines 57-113) is well-implemented:
- Global failure counter with threshold (5 failures)
- Exponential backoff with jitter on retry
- Half-open state for recovery testing
- Non-blocking state check before attempting operations

This pattern directly maps to Demarch's Go coordination services. The implementation should be a shared package, not per-service.

### Pattern B: Commit Queue for Batching Git Writes

The `_CommitQueue` concept (lines 63-303) is architecturally sound: queue writes, drain with a background task, merge non-conflicting path sets into single commits. The implementation has issues (50ms wait is too long, pop(0) antipattern) but the concept is correct.

For Go: implement as a channel-based fan-in with a bounded wait (5ms) and explicit merge logic. Use `filepath.Base` path comparison to detect conflicts.

### Pattern C: `asyncio.to_thread` Wrapping for All Git/Filesystem Operations

Every blocking operation in `storage.py` is dispatched through `_to_thread` which maps to `asyncio.to_thread`. This correctly prevents blocking the event loop for GitPython calls, file writes, and lock acquisition. The wrapping is systematic and consistent.

For Go: all Git operations via `go-git` or exec-based git should run in goroutines with proper cancellation, never synchronously in request handlers.

### Pattern D: LRU Repo Cache with Time-Based Eviction

The `_LRURepoCache` solves the problem of GitPython `Repo` object accumulation (file descriptor leaks). The eviction grace period (60 seconds) handles the case where an evicted repo is still referenced by an in-flight goroutine.

For Go: the equivalent is a `sync.Map` or channel-guarded map of `*git.Repository` objects with a background cleanup goroutine. The grace-period pattern is less necessary in Go due to explicit lifetime management, but reference counting via `sync/atomic` before closing would be the equivalent.

### Pattern E: Async File Lock with Stale Owner Detection

`AsyncFileLock` (lines 623-906) implements a cross-process file lock with:
- PID-based owner tracking via a sidecar `.owner.json` file
- Age-based staleness (180s default)
- `os.kill(pid, 0)` liveness check on Unix
- Adaptive timeout strategy (10% → exponential growth → full remaining)

This is the right approach for multi-process coordination without a central service. For Demarch's Go services, which have Intermute as the coordination kernel, a centralized lock service is preferable to filesystem locks — but if filesystem locks are needed (e.g., for git operations), this pattern is correct.

---

## Scaling Bottlenecks: What Breaks First

### Under high agent count (50+ agents):

1. The `select(Agent).where(project_id == ...)` full-project scans in `_find_similar_agents`, `_list_project_agents`, and broadcast expansion become table scans of 50+ rows, each with SequenceMatcher O(n) evaluation. Every failed agent lookup runs this scan.

2. The `func.lower(Agent.name)` pattern on the non-expression-indexed `name` column means every agent lookup (including successful ones) does a filtered scan rather than an index seek.

### Under high message volume (10,000+ messages per project):

1. `_list_inbox` joins `message_recipients` → `messages` → `agents` without a covering index for the `(agent_id, project_id, created_ts)` access pattern. The query planner must filter `project_id` from `messages` after joining from `message_recipients.agent_id`.

2. The FTS5 index grows linearly and WAL checkpointing via the checkin hook becomes more frequent, adding disk write amplification.

### Under high concurrent write load (10+ simultaneous sends):

1. SQLite's single-writer limit serializes all writes regardless of the 50-connection pool. The commit queue helps, but the 50ms batching window means each burst of concurrent sends pays 50ms overhead minimum.

2. The `AsyncFileLock` for archive writes is per-project, so concurrent sends to the same project serialize at the file lock. This is correct behavior but creates a write queue under load.

3. The `_commit_direct` function opens a fresh `Repo(str(repo_root))` on every invocation (line 1762). Under 10 concurrent sends being processed sequentially by the commit queue, this is 10 `Repo.__init__` calls per queue drain cycle. Each `Repo.__init__` reads `.git/config`, `.git/HEAD`, and `.git/index` — 3 file reads per commit.

---

## Summary Table

| Finding | Impact | Hot Path | Fix Complexity |
|---------|--------|----------|----------------|
| Pool size 50 for SQLite | Memory waste, FD pressure | Startup | Low — set to 10 |
| `func.lower(topic)` breaks index | Full scan on filtered reads | `fetch_inbox` with topic | Low — lowercase at write |
| `_find_similar_*` full scans | Latency spike on error path | `send_message`, `fetch_inbox` | Low — add LIMIT |
| `func.lower(Agent.name)` breaks index | Per-request table scan | Every tool call | Medium — expression index |
| 50ms commit queue wait | +50ms per send | `send_message` | Low — tune to 5ms |
| Closed session re-use | Reply auto-allow silently broken | `send_message` with thread | Low — fix scope |
| `pop(0)` in LRU/deque | O(n) in bounded structures | Write path | Low — use deque/OrderedDict |
| Passive checkpoint on checkin | Fragmented checkpoint I/O | All writes | Medium — background task |
| `_commit_direct` new Repo each call | 3 file reads per commit | `send_message` | Medium — use repo cache |
| Missing `(agent_id, project_id)` index | Suboptimal inbox join | `fetch_inbox` | Medium — schema change |
