# fd-performance (seed adjacent)

## Findings Index
- [P0] document.md:22 — token_id from query string joined directly into path → traversal that can corrupt/cross-contaminate entries under load
- [P0] document.md:30,44 — store writes index after file write; lookup reads file without atomic rename → torn-read window (partial file)
- [P1] document.md:33-45 — check-then-delete on _index (L39-41) not atomic under asyncio/gevent → lost/double-delete
- [P1] document.md:48-51 — purge_all removes files before clearing _index; window where lookup opens just-unlinked file and succeeds
- [P1] document.md:57 — per-process _index means cross-worker lookups always miss → in-process index gives zero benefit for most traffic
- [P2] document.md:44-45 — "fast path" still does open+read+json on every hit; index avoids only a stat, not disk I/O
- [P2] document.md:48-50 — purge_all listdir-then-remove with no error handling; concurrent store leaves orphaned file
- [P3] document.md:26 — time.time() evaluated independently at store vs lookup; TTL boundary not frozen across replicas [t]

## Findings
- **[1] P0 document.md:22** — Path traversal via unsanitized token_id breaks cache isolation.
  evidence: `return os.path.join(CACHE_DIR, token_id + ".json")`; token_id "straight from query string".
- **[2] P0 document.md:28-30,44-45** — Non-atomic file write + index update → torn-read window on hot path.
  evidence: `open(path,"w")` no atomic rename; `_index[...]=(path,expires)` set after write; reader racing the write opens partial file.
- **[3] P1 document.md:35-41** — Non-atomic check-then-delete on _index unsafe under cooperative multitasking.
  evidence: `_index.get` … `if time.time()>expires:` … `del _index[token_id]` with yield points between.
- **[4] P1 document.md:48-51** — purge_all ordering inverts safe teardown; window serves rotated-away secret.
  evidence: `os.remove(...)` loop completes before `_index.clear()`; correct order is clear index first.
- **[5] P1 document.md:57** — Per-process _index defeats the hot-path optimization on multi-worker deployments.
  evidence: context "each process has its own _index"; cross-worker requests always get entry=None.
- **[6] P2 document.md:34-45** — "fast path" comment false; every hit still does open+read+json.loads.
  evidence: after index hit, `with open(path) as f: return json.load(f)["secret"]` runs unconditionally; secret not stored in _index.
- **[7] P2 document.md:48-50** — purge_all TOCTOU gap leaks files created concurrently during purge loop.
  evidence: `os.listdir` snapshots; concurrent store after listdir writes a file not in snapshot, orphaned after clear.

## Verdict
Two P0 correctness hazards (traversal, torn-read) interact with multi-process topology to make the hot-path optimization illusory: per-worker index means universal cross-worker misses, yet every same-worker hit still reads disk. Purge ordering leaves a window serving revoked secrets.
