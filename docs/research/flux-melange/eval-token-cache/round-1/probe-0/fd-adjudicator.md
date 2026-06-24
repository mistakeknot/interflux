# fd-correctness-adjudicator (round 1, PROBE-DISAGREEMENT @ token_cache.py:48-51)

## Findings Index
- [P0] document.md:48-51 — Both claims hold but are SEQUENCED: Claim B (FileNotFoundError crash) fires on the first sibling request post-purge; Claim A (stale-secret serve) is structurally blocked because _index stores (path,expires), NOT the secret value

## Findings
- **[F1] P0 document.md:33-51** — Claim B dominates; Claim A cannot fire as stated.
  evidence: Trace process B after A's purge: L35 _index.get returns old (path,expires); L39 time.time()>expires is False (rotation precedes TTL); L44 open(path) on a file A already deleted → uncaught FileNotFoundError. lookup() never returns the secret before opening the file, and _index stores only the path (L17,L30) — it never holds the secret. So a sibling CANNOT serve the secret without a successful file open; the open fails. Claim A ("live-credential leak from warm index") is structurally impossible in THIS code; it would require _index to cache the secret value.
  Secondary: the crash hits every warm token in every sibling at once → mass-availability event until TTL ages entries out (no cross-process invalidation).

## Verdict
BOTH mechanisms are real but sequenced; Claim B (availability collapse via FileNotFoundError) is the dominant rotation-event risk. Claim A (silent revoked-secret serve) is BLOCKED by the (path,expires)-only index — it would hold only if the secret were cached in _index. This directly contradicts probe-1/F2 and the seed security finding f-007; preserve as a live disagreement on whether the dominant rotation risk is a credential leak or an availability crash.
