# fd-fusion-security-x-performance (round 1, FUSE probe; parents: fd-security, fd-performance)

## Findings Index
- [P0] document.md:33-45 — In-process index TTL check is the ONLY expiry enforcement; a process that cached a token before revocation serves it from memory for up to 300s after the file is overwritten/deleted by another process
- [P1] document.md:48-51 — purge_all clears files before index, and only the calling process's index; the fast-path skip makes deletion not equal invalidation for siblings
- [P1] document.md:20-22+33-45 — once a (possibly traversed) path is in the index, the fast path permanently launders it: even if the file is remediated, the index returns the secret until TTL
- [P2] document.md:25-30+39 — lookup checks _index.expires (the writer's clock) not the file's authoritative expires; cross-process clock skew yields divergent expiry decisions

## Findings
- **[F1] P0 document.md:33-45** — Per-process index makes revocation incomplete: a token revoked by overwriting/deleting the file stays live in every other process's _index for up to TTL.
  evidence: comment L34 "Fast path: trust the in-process index, skip the filesystem entirely"; context L57 multi-process; entry served while time.time()<=expires without re-reading the file.
  intersection_justification: Parent B (performance) introduced the index specifically to skip the filesystem stat — the optimization. Parent A (security) requires revocation propagate to every cached location before it is complete. Security alone says "no re-validation" generically; it takes the performance insight that the skip is intentional and per-process to see why the revocation gap is exactly one TTL wide across every not-yet-missed process.
- **[F2] P1 document.md:48-51** — purge_all clears files then index, and only the caller's index; siblings keep live entries pointing at deleted files; index-presence implicitly authorizes.
  evidence: os.remove loop then _index.clear(); _index module-level so clear() is process-local; context L58 purge on rotation.
  intersection_justification: B motivates the index as sole fast-path arbiter (file deletion != invalidation for others); A establishes rotation must achieve full revocation. Security alone says "revocation incomplete" without the mechanism; performance alone says "FileNotFoundError on fast path is a bug" without the security meaning of index-presence-as-authorization.
- **[F3] P1 document.md:20-22+33-45** — fast path launders an attacker-controlled traversed path for a full TTL even after out-of-band remediation.
  evidence: store registers traversed path in _index; lookup opens the already-resolved path without re-deriving/re-validating.
  intersection_justification: A identifies the unsanitized path; B explains why the violation persists (index never re-derives the path). Together they reveal TTL-duration persistence immune to remediation.
- **[F4] P2 document.md:25-30+39** — lookup uses _index.expires (writer's clock), never the file's authoritative expires; clock skew across processes serves an already-expired token as live.
  evidence: store computes expires=time.time()+TTL in writer; lookup compares against local time.time(); file expires field ignored.
  intersection_justification: B motivates reading expires from the index, not re-parsing the file; A establishes TTL as a security control needing fleet-consistent enforcement. Neither alone connects the skip of the authoritative on-disk expires to a stale-secret window.

## Verdict
F1 is the highest-value intersection: the per-process index skip, introduced purely for performance, is the precise mechanism by which a credential-rotation event fails to revoke — a gap exactly one TTL wide that scales with the number of load-balanced processes. Invisible to either parent alone.
