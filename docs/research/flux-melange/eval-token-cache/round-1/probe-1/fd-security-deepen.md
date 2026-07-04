# fd-security (round 1, DEEPEN probe @ c-crossproc-revocation)

## Findings Index
- [P1] document.md:48-51 — UPHELD: purge_all() clears only the calling process's _index; sibling processes' in-memory indices stay intact, so a revoked token authenticates in those processes for up to 300s
- [P1] document.md:44-45 — second-order: when a sibling DOES still have the file (not yet deleted) it serves the stale secret silently with no crash/log until TTL

## Findings
- **[F1] P1 document.md:48-51,16-17,57-58** — CONFIRMED. _index is a module-level dict (L17); modules are per-process, so _index.clear() in one worker leaves siblings untouched. The fast path (L34 comment) trusts the in-memory entry and returns without reading disk, so even with the backing file deleted a sibling serves the cached secret from memory until its own TTL ticks.
  evidence: L17 `_index = {}`; L43-45 returns json.load after in-memory TTL check; L48-51 clear is local; context L57-58.
- **[F2] P1 document.md:44-45** — Silent extended auth window: while the file still exists (or in the window before deletion), sibling serves the stale secret transparently; on TTL expiry the entry is dropped and the next lookup returns None — no crash, no log. The failure mode is a silent live-credential window, not an error.
  evidence: L39-42 expiry drop; L44-45 json.load(f)["secret"].

## Verdict
UPHELD. purge_all achieves full eviction only in the process that calls it; siblings retain _index entries and bypass deleted files via the in-memory fast path, silently serving the revoked credential until TTL. Worst-case window: 300s, no observable signal.
