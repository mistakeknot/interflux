# fd-distant-formal-methods (round 1, STEER-WIDE probe; distant: formal methods / invariants)

## Findings Index
- [P0] document.md:36-45,25-30 — No single source of truth: _index and the filesystem are two representations of one abstract map with no designated canonical copy and no reconciliation function (the root invariant absence)
- [P1] document.md:25-30 — store is not atomic: file write and index update are two steps; a crash between them breaks _index[t] ↔ file_exists in one direction
- [P1] document.md:44-45 — lookup never checks _index[t].expires == file["expires"]; a concurrent store breaks the record-consistency sub-invariant
- [P2] document.md:36-41 — lookup deletes the index entry on expiry but leaves the file: abstract DELETE postcondition (file gone) not established
- [P3] document.md:25-30 — store writes file before index: transient window where a stored token is invisible to a concurrent lookup (non-linearizable) [t]

## Findings
- **[F1] P0 document.md:33-45,25-30** — No canonical representation; _index and filesystem are dual copies with no master and no rehydrate function. After a process restart _index is empty while disk is non-empty; the coherence invariant is irreparably broken at cold start. This is the ROOT CAUSE; the cross-process FileNotFoundError, the stale-secret window, and the expired-file leak are all symptoms.
  evidence: store writes disk then index (L28-30); lookup reads index for expiry and disk for secret (L36-45); no load/rehydrate exists. Invariant: ∀t. _index[t] ↔ file_exists(_path_for(t)) ∧ _index[t].expires==file(t)["expires"].
- **[F2] P1 document.md:28-30** — store non-atomic: kill between file commit (L29) and index insert (L30) leaves file-present/index-absent.
  evidence: with open(...) json.dump completes; `_index[token_id]=...` never runs.
- **[F3] P1 document.md:39-45** — lookup conflates two representations: trusts _index for liveness, file for value, validates neither against the other.
  evidence: L39 uses _index expires; L45 returns file secret; no cross-check.
- **[F4] P2 document.md:36-41** — silent partial delete: expiry drops index entry, leaves file → file leaks until purge_all.
  evidence: del _index[token_id] (L41); file untouched.

## Verdict
The single most important missing invariant: the dual-representation coherence invariant (_index ↔ file agreement) is never established, never maintained under interleavings, and has no guardian. Every concrete bug found by the other lenses is a symptom of this one structural absence. This is the elegant root-cause/taste framing of the same family.
