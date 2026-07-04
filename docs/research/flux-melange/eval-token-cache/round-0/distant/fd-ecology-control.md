# fd-ecology-control (seed distant: ecology / control systems)

## Findings Index
- [P0] document.md:22 — Path traversal via unsanitized token_id = foreign-species introduction through a gap in the habitat fence
- [P0] document.md:33-45 vs context:57-58 — Multi-process _index divergence = inter-deme signal extinction; revocation reaches disk but not sibling in-memory populations
- [P1] document.md:39-41 — TTL checked at read against time.time(); clock skew/NTP = control loop with sensor clock drifting from plant clock
- [P1] document.md:48-51 vs context:58 — purge_all removes files then clears only local index; siblings hold ghost-population entries to deleted files
- [P2] document.md:43-45 — Fast path returns file secret without re-checking file's own expires = delayed observer reporting last season's density
- [P2] document.md:17,30,41 — module-level _index dict, no lock; multi-step read-check-delete = two controllers actuating one plant variable without a mutex
- [P3] document.md:13 — hardcoded /var/run/tokcache, no configurability = single fixed habitat, no isolation/migration path [t]

## Findings
- **[F1] P0 document.md:22** — Path traversal (invasion through unguarded habitat boundary).
  evidence: `os.path.join(CACHE_DIR, token_id + ".json")`; token_id raw from query string; `../../../etc/cron.d/evil` escapes.
- **[F2] P0 document.md:33-45 vs context:57-58** — Cross-process revocation signal extinction (inter-deme isolation → permanent stale belief).
  evidence: `_index` module-level; `purge_all` calls `_index.clear()` in one process only; siblings keep live entries up to 300s.
- **[F3] P1 document.md:39,26** — Clock-reference mismatch write-time vs read-time (control-loop sensor drift).
  evidence: `expires = time.time()+TTL_SECONDS` at store; `if time.time()>expires` at lookup; NTP step shifts expiry.
- **[F4] P1 document.md:48-51 vs context:58** — Ghost population: index entries survive with deleted backing files → FileNotFoundError on lookup, uncaught.
  evidence: purge removes files then `_index.clear()` locally; process B's _index holds paths to deleted files; `open(path)` raises.
- **[F5] P2 document.md:43-45** — File contents not re-validated against own expires (stale observer lag).
  evidence: comment L43 "return without re-reading or re-validating the file"; `json.load(f)["secret"]` ignores file expires.
- **[F6] P2 document.md:17,35,39-41** — Unsynchronized multi-step index mutation (competing controllers on shared plant).
  evidence: `_index.get` then `del _index[token_id]` non-atomic; concurrent store between them silently deleted; double-del raises KeyError.

## Verdict
Deepest flaw is architectural: a fast-path local belief (_index) coupled to shared-disk ground truth with no cross-process propagation for revocation signals, making every rotation a partial intervention that leaves sibling processes infected with stale state for a full TTL. Path traversal is the acute failure; inter-deme signal extinction is the chronic coherence pathology.
