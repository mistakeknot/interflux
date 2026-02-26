# Flux-Drive Correctness Review: mcp_agent_mail

**Reviewer:** Julik (fd-correctness agent)
**Date:** 2026-02-24
**Target:** `/home/mk/projects/Demarch/research/mcp_agent_mail/src/mcp_agent_mail/`
**Purpose:** Identify correctness patterns to adopt and bugs to avoid when building similar systems in Go.

---

## Declared Invariants

Before analyzing, I enumerate the invariants the system is trying to maintain:

1. **Message atomicity** — A message exists in both SQLite (queryable) and the Git archive (auditable) or in neither.
2. **Agent uniqueness** — Exactly one Agent row per (project_id, name) pair (case-insensitive).
3. **Project uniqueness** — Exactly one Project row per slug.
4. **Archive exclusivity** — Only one writer holds `archive_write_lock` per project at a time.
5. **Commit serialization** — Git commits to the same project root are serialized (no concurrent `index.lock` conflicts beyond what retry handles).
6. **Reservation consistency** — An active file reservation visible in SQLite must also be reflected in Git archive; the inverse must also hold.
7. **Lock liveness** — Stale advisory locks from dead processes must be detectable and cleanable.

---

## Finding Index

| Severity | ID | Section | Title |
|----------|-----|---------|-------|
| P1 | CC-01 | Dual-Write | SQLite commit succeeds but Git write crashes — message visible in DB only |
| P1 | CC-02 | Commit Queue | Batching merges futures across requests — one failure fails all callers |
| P1 | CC-03 | `_ensure_repo` | `needs_init` used outside lock scope — TOCTOU on new-repo initialization |
| P2 | CC-04 | `_get_or_create_agent` | UPDATE after re-fetch re-uses stale session across IntegrityError boundary |
| P2 | CC-05 | Circuit Breaker | `_record_circuit_failure` accumulates for non-transient errors — masks real bugs |
| P2 | CC-06 | Pool Size | 50-connection pool against a single-writer SQLite — queue buildup under contention |
| P2 | CC-07 | `_ensure_repo` fast path | Cache peek outside any lock — returns evicted/closed Repo |
| P3 | CC-08 | `_update_thread_digest` | File-lock per thread digest but no lock covering concurrent write + Git commit |
| P3 | CC-09 | Commit Queue stop() | Sentinel request is a real `_CommitRequest` — can corrupt if settings checked |
| P3 | CC-10 | `is_dirty` guard | `is_dirty(index=True, working_tree=True)` may skip commit when only index is staged |
| P3 | CC-11 | `_is_lock_error` | Matches "locked" anywhere in message — misclassifies unrelated errors as retryable |

---

## P1 Findings

### CC-01: Dual-Write Crash Window — Message Visible in DB Only

**File:** `app.py`, `_deliver_message` (~line 4476–4542)
**Severity:** P1 — Silent data corruption, invariant #1 broken

#### What the code does

```python
# Inside _archive_write_lock(archive):
message = await _create_message(...)           # SQLite COMMIT happens here
# ... build frontmatter ...
await write_message_bundle(archive, ...)       # Git write + commit happens here
```

`_create_message` calls `session.commit()` (line 3389) inside its own `get_session()` context before `write_message_bundle` is called. The archive write lock serializes filesystem mutations within a single process, but it does not wrap the SQLite commit.

#### Concrete failure interleaving

```
T=0   _deliver_message acquires archive_write_lock
T=1   _create_message executes session.commit() → message row ID=42 persists in SQLite
T=2   Server process crashes (OOM, SIGKILL, power loss, EMFILE)
T=3   Git archive never written; process restarts
T=4   fetch_inbox finds message ID=42 in SQLite
T=5   No corresponding file in archive — audit log forever incomplete
```

The inverse crash (archive written, SQLite not committed) cannot occur because `_create_message` commits first, but the forward crash (DB committed, Git not written) is the common case since the process is more likely to fail after the fast DB operation than before the slower filesystem+git operation.

#### Why this matters for a Go port

The pattern of "commit to durable store A, then write to durable store B" inherently has a crash window. The only robust mitigations are:

1. **Write-ahead tombstoning** — Write a pending-commit record to SQLite before the Git step; clear it after. On startup, scan and replay pending records.
2. **Accept eventual consistency** — Treat the Git archive as a best-effort audit trail, not a consistency boundary. Document this explicitly.
3. **Saga with compensating action** — If Git fails after SQLite succeeds, mark the message as `archive_failed` and surface it in health_check.

The current code has none of these. A Go implementation should choose one explicitly and enforce it.

---

### CC-02: Commit Queue Batch Failure Propagates to All Batched Callers

**File:** `storage.py`, `_CommitQueue._process_batch` (~lines 278–303)
**Severity:** P1 — One failing file path causes multiple unrelated operations to error

#### What the code does

```python
if can_batch and len(requests) <= 5:
    # Merge into single commit
    merged_paths = [all paths from all requests]
    try:
        await _commit_direct(repo_root, settings, combined_message, merged_paths)
        for req in requests:
            req.future.set_result(None)   # All succeed together
    except Exception as e:
        for req in requests:
            req.future.set_exception(e)   # All fail together
```

When four agents concurrently commit non-overlapping files and one of those files is, say, corrupt or unreadable, `_commit_direct` fails, and all four `asyncio.Future` objects receive the exception. Three innocent agents get an error they have no way to diagnose.

#### Concrete failure interleaving

```
Agent A: commits projects/proj1/messages/2026/02/msg-100.md
Agent B: commits projects/proj1/agents/BlueLake/profile.json
Agent C: commits projects/proj1/agents/RedStone/inbox/...
Agent D: commits projects/proj1/file_reservations/abc.json (file permissions 000 — unreadable by git)

Queue batches A+B+C+D (no path overlap — can_batch=True)
_commit_direct → git.index.add(all_paths) → OSError on D's file
A, B, C all receive OSError "permission denied" for a file they never touched
Their callers (send_message, register_agent) surface this as message delivery failure
```

#### Fix pattern

Process each request individually on exception, falling back to sequential commits:

```python
try:
    await _commit_direct(repo_root, settings, combined_message, merged_paths)
    for req in requests:
        req.future.set_result(None)
except Exception:
    # Batch failed — fall back to sequential to isolate the failing request
    for req in requests:
        try:
            await _commit_direct(req.repo_root, req.settings, req.message, req.rel_paths)
            req.future.set_result(None)
        except Exception as e:
            req.future.set_exception(e)
```

This is the standard approach in Go's errgroup as well: if a combined operation fails, retry individually to preserve isolation.

---

## P2 Findings

### CC-03: `needs_init` Scoping Bug — TOCTOU on New Repo Initialization

**File:** `storage.py`, `_ensure_repo` (~lines 1125–1151)
**Severity:** P1 borderline / P2 — Race creates duplicate initial commits or `UnboundLocalError`

#### The code

```python
async with _get_repo_cache_lock():
    ...
    if git_dir.exists():
        repo = Repo(str(root))
        _REPO_CACHE.put(cache_key, repo)
        return repo                      # early return, needs_init NOT set

    repo = await _to_thread(Repo.init, str(root))
    _REPO_CACHE.put(cache_key, repo)
    needs_init = True                    # only set on new-repo path

# Lock released here
if needs_init:                           # NameError if existing-repo path taken
    ...
    await _commit(repo, settings, "chore: initialize archive", [".gitattributes"])
```

If the `git_dir.exists()` branch is taken, `needs_init` is never assigned, and `if needs_init:` raises `UnboundLocalError` at runtime. Python does not initialize variables to `False` automatically. This is currently masked because the early `return repo` in the exists-branch exits before reaching `if needs_init:`. But that is fragile coupling: if someone adds code between the lock release and `if needs_init:`, or refactors the early return, the `UnboundLocalError` surfaces immediately.

Additionally: even if the `needs_init = True` path is taken, the `_commit` call inside `if needs_init:` happens outside the cache lock but uses the `repo` that is now cached and accessible to other coroutines. If a second coroutine acquires the cache and finds the repo while initialization is in flight, it may observe an uninitialized git repo.

#### Fix

```python
needs_init = False                         # Always initialize
async with _get_repo_cache_lock():
    ...
    if git_dir.exists():
        repo = Repo(str(root))
        _REPO_CACHE.put(cache_key, repo)
    else:
        repo = await _to_thread(Repo.init, str(root))
        _REPO_CACHE.put(cache_key, repo)
        needs_init = True
```

For the initialization race, either hold the cache lock through the first commit (blocking other users temporarily) or use a per-path `asyncio.Event` to signal "initialization complete" before returning the repo to other callers.

---

### CC-04: `_get_or_create_agent` Stale Session Across IntegrityError Boundary

**File:** `app.py`, `_get_or_create_agent` (~lines 3069–3131)
**Severity:** P2 — Potential stale reads or DetachedInstanceError in the UPDATE path

#### The pattern

```python
async with get_session() as session:
    for _attempt in range(5):
        result = await session.execute(select(Agent)...)
        agent = result.scalars().first()
        if agent:
            # UPDATE path
            agent.program = program
            ...
            await session.commit()
            await session.refresh(agent)
            break

        # INSERT path
        candidate = Agent(...)
        session.add(candidate)
        try:
            await session.commit()
            ...
        except IntegrityError:
            await session.rollback()           # session state invalidated
            with suppress(Exception):
                session.expunge(candidate)

            if explicit_name_used:
                result = await session.execute(select(Agent)...)   # re-query same session
                agent = result.scalars().first()
                ...
                agent.program = program        # modify re-fetched agent
                await session.commit()         # commit on session that had a rollback
```

After `session.rollback()`, the SQLAlchemy session is in a clean state, but any ORM objects that were loaded before the rollback are "expired". The code re-queries within the same session object, which is correct for getting fresh data. However, this pattern keeps one session open across multiple commit/rollback cycles within the retry loop. In SQLAlchemy async with SQLite, a session that has had a rollback and then attempts a new `begin` implicitly may have subtly different transaction isolation behavior depending on the DBAPI layer.

The deeper issue is that `session.add(agent)` after re-fetching the agent (line 3122) adds a detached-style object to the session. If the session's identity map already has this object from the re-query, this is a no-op; if the `result.scalars().first()` returned a new Python object, the session may create a duplicate merge attempt. The `expire_on_commit=False` setting (configured in `db.py` line 536) means committed objects are not expired, which helps but also means stale data can be returned from the identity map for the re-query.

#### Pattern recommendation for Go

Keep a single transaction per logical attempt. Never reuse the same DB handle/connection across a commit-rollback-retry cycle in the same function scope. Open a fresh transaction on each retry iteration.

---

### CC-05: Circuit Breaker Counts Non-Transient Errors as Failures

**File:** `db.py`, `retry_on_db_lock` (~lines 263–310)
**Severity:** P2 — Circuit trips on logic errors, masking bugs as "database under load"

#### The pattern

```python
except (OperationalError, SATimeoutError) as e:
    error_msg = str(e)
    is_lock = _is_lock_error(error_msg)
    is_pool = _is_pool_exhausted_error(e)

    if not (is_lock or is_pool) or attempt >= max_retries:
        if use_circuit_breaker:
            await _record_circuit_failure()    # ← circuit incremented for ALL errors
        raise
```

When the condition `not (is_lock or is_pool)` is true — meaning this is a real, non-transient `OperationalError` (e.g., schema mismatch, corrupted database, missing table) — the code increments the circuit breaker failure counter before re-raising. Five such non-transient errors within 30 seconds open the circuit breaker, and subsequent tool calls immediately fail with `CircuitBreakerOpenError` instead of the original informative error.

An operator sees "circuit breaker open" rather than "table 'agents' does not exist". The circuit then resets after 30 seconds, not when the underlying problem is fixed.

#### Fix

Only count retried-and-exhausted transient lock errors as circuit breaker failures. Non-transient errors should be raised immediately without touching the circuit state:

```python
if not (is_lock or is_pool):
    raise   # do NOT record circuit failure for non-transient errors
if attempt >= max_retries:
    await _record_circuit_failure()
    raise
```

---

### CC-06: 50-Connection Pool Against a Single-Writer SQLite

**File:** `db.py`, `_build_engine` (~line 391)
**Severity:** P2 — Pool size creates false confidence; actual concurrency is serialized at SQLite

#### The configuration

```python
pool_size = settings.pool_size if settings.pool_size is not None else (50 if is_sqlite else 25)
max_overflow = settings.max_overflow if settings.max_overflow is not None else (4 if is_sqlite else 25)
```

SQLite allows only one writer at a time regardless of how many connections are open. 54 connections can all attempt concurrent writes; they will queue at the SQLite busy_timeout layer (60 seconds each). Under 54 concurrent writers, the 55th connection blocks on pool acquisition (45s timeout) while 54 others each wait up to 60s for the SQLite write lock. The exponential backoff in `retry_on_db_lock` adds further delay per-connection.

The actual safe pool size for SQLite is 1–3 connections with autocommit reads and serialized writes, or WAL mode with bounded writer concurrency. The current pool size is appropriate for PostgreSQL, not SQLite.

This does not cause data corruption but causes thundering-herd behavior under load: all 54 connections attempt the write lock simultaneously, driving busy_timeout to the maximum for every operation, and the 7-retry exponential backoff in `retry_on_db_lock` (up to ~12.7s per call) compounds across concurrent callers.

#### Pattern recommendation for Go

In a Go system targeting SQLite: use `MaxOpenConns(1)` for write operations. The Demarch MEMORY.md already documents this pattern: `MaxOpenConns(1), WAL mode, 5s busy timeout (via pkg/db)`. The mcp_agent_mail pool size contradicts this established practice.

---

### CC-07: Repo Cache Fast-Path Returns Evicted Repo Outside Any Lock

**File:** `storage.py`, `_ensure_repo` (~lines 1106–1109)
**Severity:** P2 — Returns closed `Repo` object under concurrent LRU eviction

#### The code

```python
# Fast path: check cache without lock using peek() which doesn't modify LRU order
cached = _REPO_CACHE.peek(cache_key)
if cached is not None:
    return cached
```

`peek()` reads `_REPO_CACHE._cache` without holding `_REPO_CACHE_LOCK`. Concurrently, another coroutine may hold the cache lock and be executing `_REPO_CACHE.put(new_key, new_repo)`, which triggers eviction (`_order.pop(0)`, `_cache.pop(oldest_key)`), schedules the peeked repo into `_evicted`, and eventually calls `repo.close()` after the grace period.

The peeking coroutine now holds a reference to a `Repo` that is `Repo.closed` (or being closed). Any subsequent `repo.index.add(...)` or `repo.iter_commits(...)` call will raise `git.exc.InvalidGitRepositoryError` or an OSError.

#### Concrete interleaving

```
Coroutine A: peek() returns repo_for_proj_X (cache has 16 entries, proj_X is LRU)
Coroutine B: acquires cache lock, puts repo_for_proj_Y → evicts proj_X
  → _evicted.append((repo_for_proj_X, now))
Coroutine C (60s later, cleanup run): repo_for_proj_X.close()
Coroutine A: repo_for_proj_X.index.add(...) → OSError: repository is closed
```

The grace period (60s) reduces the probability but does not eliminate it, especially under load where cleanup runs at `EVICTION_GRACE_SECONDS`.

#### Fix

Eliminate the lock-free fast path, or hold a reference count (not `sys.getrefcount`) using a local dict of "in-use" refs that prevents eviction while a coroutine holds a reference. In Go, this is cleanly handled with a sync.Map and atomic reference counts.

---

## P3 Findings

### CC-08: Thread Digest File Lock Does Not Cover the Git Commit

**File:** `storage.py`, `_update_thread_digest` (~lines 1364–1375)

```python
async with AsyncFileLock(lock_path):
    await _to_thread(_append)              # file write protected by lock
# lock released here
return digest_path.relative_to(archive.repo_root).as_posix()
# caller then passes this path to _commit (inside write_message_bundle)
```

The advisory lock on `{thread_id}.md.lock` covers the `_append` call but is released before `_commit` is called. Two concurrent messages to the same thread can:

1. Both acquire the lock in sequence, both append their content correctly.
2. Both pass the digest path to `write_message_bundle`.
3. Both call `_commit` with the same digest path but different batches of `rel_paths`.

Since `_commit_direct` uses a per-project `commit.lock`, the two commits are serialized. The second commit will run `index.add([..., digest_path])` which picks up the current state of the file — containing both entries — and produces a single commit that includes both writers' content. This is actually correct behavior. But if the commit queue batches the two commits together, both callers get a single merged commit containing the correct digest file. This is safe.

The actual risk is if the commit queue batches them but the merged `_commit_direct` fails (CC-02 scenario) — then neither append is reflected in git even though both writes completed on disk.

Severity P3 because the risk only materializes through CC-02.

---

### CC-09: Sentinel Request in `_CommitQueue.stop()` Uses `settings=None`

**File:** `storage.py`, `_CommitQueue.stop()` (~lines 129–134)

```python
with contextlib.suppress(asyncio.QueueFull):
    self._queue.put_nowait(_CommitRequest(
        repo_root=Path("/dev/null"),
        settings=None,          # deliberately invalid sentinel
        message="",
        rel_paths=[],
    ))
```

The `_process_loop` correctly checks `if first.settings is None: continue` to skip sentinels. However, the sentinel is also inserted into the batch-collection loop where items are drained without the sentinel check:

```python
while len(batch) < self._max_batch_size and time.monotonic() < deadline:
    try:
        request = self._queue.get_nowait()
        if request.settings is not None:  # ← sentinel check present
            batch.append(request)
    except asyncio.QueueEmpty:
        ...
```

The check is present here too. The deeper risk: if `stop()` is called while a batch is being processed that has exactly 9 requests (batch size 10 limit), the sentinel will be consumed by the secondary `get_nowait()` drain, skipped (settings is None), and the processor may then block on the next `await asyncio.wait_for(self._queue.get(), ...)` because there are no more items and `_stopped=True` is checked at the top of the while loop, not inside the wait. This is a subtle shutdown latency issue rather than a correctness bug.

A cleaner sentinel pattern is to use a dedicated `asyncio.Event` for shutdown signaling rather than poisoning the queue with an invalid object.

---

### CC-10: `is_dirty` Check May Skip Legitimate Commits

**File:** `storage.py`, `_perform_commit` (~line 1767)

```python
def _perform_commit(target_repo: Repo) -> None:
    target_repo.index.add(rel_paths)
    if target_repo.is_dirty(index=True, working_tree=True):
        ...
        target_repo.index.commit(...)
```

`is_dirty(index=True, working_tree=True)` returns `True` if there are staged or unstaged changes. After `index.add(rel_paths)`, the index should have staged changes unless all `rel_paths` were already identical to the HEAD commit. If files were written but their content is byte-for-byte identical to the last commit (e.g., agent profile re-registration with no field changes), `index.add` stages the file but `is_dirty` returns `False` because the content hash matches.

The result: the caller's `asyncio.Future` resolves successfully, but no commit was created. If the system relies on "every send_message produces a commit" for audit trail completeness, this invariant is silently violated.

Fix: check `target_repo.index.diff("HEAD")` instead of `is_dirty`, or always commit regardless of dirty state (git allows empty commits with `--allow-empty`, not used here).

---

### CC-11: `_is_lock_error` Matches "locked" Anywhere in Error String

**File:** `db.py`, `_is_lock_error` (~lines 197–208)

```python
return any(
    phrase in lower_msg
    for phrase in [
        "database is locked",
        "database is busy",
        "locked",                    # ← matches "deadlocked", "unlocked", "table is locked"
        "unable to open database",
        "disk i/o error",
    ]
)
```

The bare `"locked"` substring matches `"deadlocked"`, `"table_lock_mode"`, `"unlocked"`, or any error message from application code that happens to contain the word. PostgreSQL (if someone switches the backend) uses "row-level lock" in messages. This misclassifies non-retryable errors as transient lock contention, causing the retry loop to exhaust all attempts and then increment the circuit breaker unnecessarily (compounding CC-05).

Fix: use the more specific phrases only and remove the bare `"locked"` entry. For SQLite specifically, the only messages that matter are `"database is locked"` and `"database is busy"`.

---

## Patterns Worth Adopting

These patterns are well-designed and worth replicating in Go:

### Adaptive lock acquisition with stale owner detection

`AsyncFileLock._cleanup_if_stale()` checks both liveness (`os.kill(pid, 0)`) and age. This is the correct dual-condition approach: a lock can be stale because the owner died OR because the lock is ancient regardless of whether the PID was recycled. Go ports should implement the same dual condition, using `/proc/<pid>/status` existence check or `os.FindProcess` + `proc.Signal(syscall.Signal(0))`.

### Process-level asyncio.Lock wrapping a file lock

The combination of an asyncio.Lock (in-process, prevents concurrent acquisition by coroutines in the same event loop) with a SoftFileLock (cross-process, advisory) is a correct two-level locking strategy. In Go: use a `sync.Mutex` for in-process serialization plus `github.com/gofrs/flock` for cross-process advisory locks.

### IntegrityError → rollback → re-query pattern for upserts

`_ensure_project` (app.py line 2126–2135) catches `IntegrityError` after an optimistic INSERT, rolls back, and re-queries. This is the correct pattern for concurrent upserts without a serializable transaction. The Go equivalent using `database/sql` is:

```go
_, err := db.ExecContext(ctx, "INSERT OR IGNORE INTO projects (slug, human_key) VALUES (?, ?)", slug, key)
// then SELECT regardless of err
```

Or using SQLite's `INSERT OR REPLACE` / `ON CONFLICT DO NOTHING`.

### LRU repo cache with time-based (not refcount-based) eviction

The decision to use time-based eviction instead of `sys.getrefcount()` is correct. Reference counts in CPython are unreliable for this purpose because stack frames, local variables, and iteration hold references that inflate the count temporarily. The MEMORY.md note confirms this was discovered through a real bug. Go ports using GitPython-equivalent libraries (e.g., go-git) should use a similar time-since-last-use eviction policy, not reference counting.

### Proactive FD headroom check before repo creation

`proactive_fd_cleanup(threshold=100)` runs before creating a new `Repo` object to ensure the process has 100 FDs of headroom. This is a good defensive pattern. Go equivalent: call `syscall.Getrlimit(syscall.RLIMIT_NOFILE, &rlim)` and compare to `len(os.ReadDir("/proc/self/fd"))` or just maintain a counter of open git handles.

### Per-project commit lock derived from file paths

`_commit_lock_path()` inspects the `rel_paths` to determine if all files belong to a single project, and if so, uses a per-project commit lock (`projects/{slug}/.commit.lock`) instead of a global repo lock. This is a smart concurrency improvement: cross-project commits are serialized only at the repo level, not at the project level. Go ports should adopt this pattern.

---

## Transaction Safety Summary

| Write Path | Transaction Scope | Partial Commit Risk |
|-----------|------------------|---------------------|
| `_ensure_project` | Per-attempt, with IntegrityError retry | Low — idempotent re-query handles it |
| `_get_or_create_agent` | Single session, multiple commit/rollback | Medium — stale session across boundary (CC-04) |
| `_create_message` | Single session, flush+commit atomically | Low within SQLite; high across SQLite+Git (CC-01) |
| `_create_file_reservation` | Single session, single commit | Low |
| Git commits via queue | Batch across multiple callers | High — batch failure fails all (CC-02) |
| Thread digest | File-locked write, separate Git commit | Low (sequential by project commit.lock) |

---

## Race Condition Summary for Go Port

When building a Go equivalent, the following are the concrete concurrency constraints:

1. **SQLite write serialization** — Use `MaxOpenConns(1)` with `WAL` mode. Pool size of 50 for SQLite is misleading and creates thundering-herd behavior.

2. **Upsert pattern** — Use `INSERT OR IGNORE` + unconditional `SELECT`, not optimistic INSERT + IntegrityError catch. The latter requires session management across rollback boundaries.

3. **Dual-write atomicity** — Accept that SQLite-first + Git-second has a crash window. Implement a startup recovery scan that detects messages in SQLite with no corresponding Git commit and either replays the Git write or marks them `archive_pending`.

4. **Batch commit failure isolation** — Never propagate a single file error to all callers in a batch. Fall back to sequential on batch failure.

5. **Repo handle lifetime** — Track repo handles with reference counts (atomic integers), not LRU eviction by time. Close only when refcount reaches zero. This is safer than time-based eviction which can close a handle that is actively in use.

6. **Circuit breaker scope** — Only count retried-and-exhausted transient errors as circuit failures, not permanent errors. Permanent errors should surface immediately with their original message.

---

*Verdict: needs-changes. Three correctness bugs (CC-01, CC-02, CC-03) warrant fixes before this pattern can be used as a reference implementation. The advisory locking strategy and upsert patterns are well-designed and worth adopting.*
