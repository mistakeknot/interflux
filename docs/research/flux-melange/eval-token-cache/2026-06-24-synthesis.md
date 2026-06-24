---
artifact_type: melange-synthesis
method: flux-melange
target: "tests/fixtures/melange/fixture-token-cache/document.md"
target_description: "A small Python service-side cache for short-lived API tokens (token_cache.py): in-process index over per-token JSON files, TTL-based expiry, purge_all on rotation."
goal: "surface the highest-risk and most novel weaknesses, especially any that only appear at the intersection of two concerns"
weights: balanced
rounds_run: 2
halt_reason: BUDGET
total_fusions: 1
emergent_findings: 0
date: 2026-06-24
---

# Flux-Melange Synthesis — token_cache.py (the eye of distance)

The loop seeded two adjacent lenses (security, performance) plus one distant lens (ecology / control-systems), then ran one adaptive round driven entirely by the round-0 heat map: a PROBE-DISAGREEMENT on the purge region, a DEEPEN on the cross-process revocation cluster, a FUSE of security × performance (the highest-complementarity non-redundant pair), and a reserved STEER-WIDE into formal methods. A single cheap verify pass on the high-novelty/high-risk subset then **overturned the headline the fusion proposed** — which is the most important result in this report.

Scores below are the synthesis re-scoring of the merged ledger (the per-round assayer numbers were triage-grade). Ranking is by HEAT (novelty × risk.product), never severity.

## 1. Novelty × Risk Frontier

The Pareto front of *upheld* findings on (novelty, risk.product):

- **f-027 — purge-event availability collapse (novelty 3, risk 6 = heat 18). THE headline.** After `purge_all()` runs in one process during rotation, every sibling process still holds warm `_index` entries whose backing files were just deleted. `_index` stores only `(path, expires)` — **not the secret** — so the next sibling `lookup()` passes the in-memory TTL check (L39), reaches `open(path)` (L44) on a deleted file, and raises an **uncaught `FileNotFoundError`**. This fires for every warm token in every sibling simultaneously, until TTL ages the entries out (no cross-process invalidation). Risk decomposition: blast_radius 3 (whole service, all workers), likelihood 2 (every rotation event under load). severity (for reference only): the seed lenses ranked the purge issues P1/P2. Lens: fd-correctness-adjudicator (the PROBE-DISAGREEMENT probe). This finding only exists because the controller spent a directive adjudicating a contradiction the seed lenses left open.
- **f-001 — path traversal (novelty 0, risk 9 = heat 0; the max-risk corner).** `token_id` from the query string is concatenated into a filesystem path with no sanitization (`os.path.join(CACHE_DIR, token_id + ".json")`, L22). blast 3 × likelihood 3. Zero novelty (all three seed lenses independently found it — commodity), but it anchors the high-risk/high-confidence corner of the frontier: trust it, fix it first, don't be excited by it.
- **f-007/f-008 — cross-process revocation gap (novelty 2, risk 6 = heat 12).** `purge_all()` clears only the calling process's `_index` (L51); siblings retain entries for up to one TTL (300s). NOTE the live disagreement with f-027 below — both describe the same code region but disagree on whether the failure is a *silent credential leak* (f-007/f-008) or an *availability crash* (f-027).
- **f-004 — arbitrary file overwrite (novelty 1, risk 6 = heat 6).** `store()` writes attacker-influenceable JSON to an unsanitized path (traversal + write).
- **f-028 — missing dual-representation invariant (novelty 3, risk 2 = heat 6, taste +2).** Root-cause finding; see Taste Calls.

## 2. Top Fusions

**fd-security × fd-performance — ZERO net emergent findings (a negative result).** This is the section the mode exists for, and here it is a *teaching* negative result.

The fusion probe proposed f-022 as its emergent prize: "the fast path skips re-reading/re-validating the file, so a revoked credential keeps authenticating from the warm index" — i.e. the classic security-cost-of-a-performance-optimization interaction. The emergence gate promoted it (novelty floored at 3: both parents touched the lookup region but neither connected the optimization to the revocation gap).

**The verify pass refuted it.** Reading the actual source: `lookup()` does *not* skip the file read — L44-45 always does `open(path)` then `json.load(f)["secret"]`. The index skips only a `stat` (the L16 comment), and crucially **the secret is never cached in `_index`** (it stores `(path, expires)`, L17/L30). So the "serve a stale secret from the warm index without touching disk" mechanism is *factually inverted*: a sibling cannot return the secret without opening the file, and after purge that open *crashes*. The verifier also judged the intersection_justification fails the genuinely-requires-both test — a security-only view of "per-process index + purge-local-only" already names the cross-process gap; no performance framing is required.

Net: the fusion's other findings (f-023 purge-local-only, f-024 traversal-launder, f-025 clock-skew) were either demoted to convergence (a parent already had them) or low-heat. **Emergent yield = 0/1.** The honest melange verdict: security × performance is *independent here* once you read the code correctly — the interaction the goal was hunting for does not exist in this implementation, because the optimization is shallower (skip a stat) than it appears (skip the read). The real prize, f-027, came from the PROBE-DISAGREEMENT adjudicator, not the fusion.

## 3. Taste Calls

- **f-028 (+2, asymmetry) — the elegant root cause.** `_index` and the on-disk files are two representations of one abstract map `token_id → (secret, expires)` with no designated source of truth, no rehydrate-on-restart, and no enforced coherence invariant. Every concrete bug — the purge crash (f-027), the cross-process gap (f-007), the expired-file leak (f-029), cold-start blindness — is a symptom of this one structural absence. The taste call: a single write-through wrapper or a dataclass making the dual-write invariant explicit would prevent the whole class. Surfaced by the STEER-WIDE formal-methods lens. This is the "elegant fix that dissolves several findings at once" the severity-sorted view would bury at the bottom (it is P1/P3 risk in isolation).
- **f-021 (−1, smell) — `import hashlib` is dead.** Evidence of an abandoned safe-filename design (hash the token_id) that would have closed the traversal. A smell that points at the fix.

## 4. Convergence Spine (kept, demoted)

High-confidence commodity — trust it, don't headline it:
- **Path traversal (f-001 / f-002 / f-003):** 3 lenses, 2 distance tiers (adjacent + distant) → novelty 0. The most-converged finding in the run; also the highest raw risk. Maximum confidence.
- **Cross-process revocation (f-007 security / f-008 ecology, confirmed by DEEPEN f-026):** converged across an adjacent and a distant lens then independently confirmed — high confidence on the *region*, though its *consequence* is disputed (see §5).
- **Non-atomic index race (f-013 performance / f-015 ecology):** converged, low heat.

## 5. Live Disagreements (open at halt)

- **`token_cache.py:44-51` — silent credential leak vs. availability crash.** The seed security and ecology lenses (f-007/f-008) framed the post-rotation sibling state as "still serves the revoked secret" — a confidentiality failure. The adjudicator (f-027) and the verifier showed that, *for this code*, the sibling cannot serve the secret (it isn't cached) and instead crashes on the deleted file — an availability failure. These are not reconcilable as stated: the security framing assumes a secret-caching index that this code does not have. **Resolution: f-027 is correct about the literal code; f-007/f-008 describe the bug this code would have if `_index` cached the secret (a plausible "optimization" a maintainer might add — which would silently convert the crash into exactly the credential leak the goal was hunting).** Left open because it is the single most decision-relevant ambiguity in the file.

## Spice Trail (audit of how the loop moved)

- **Round 0 (seed).** 3 lenses (fd-security, fd-performance, fd-ecology-control), 21 findings, 14 new clusters, yield 14, novel_cluster_rate 0.67. Heat map ranked purge_all (:48-51) and the lookup fast path (:33-46) hottest; flagged fd-security × fd-performance as the top non-redundant complementary pair (each lens's primitive sits in the other's failure_mode); opened one disagreement region at the purge.
- **Round 1 (adaptive).** Controller emitted 4 directives from the round-0 ledger:
  - PROBE-DISAGREEMENT @ :48-51 (weight 0.20) — "serves stale secret vs crashes?" → **produced f-027, the eventual headline.** Rationale: a high-risk region with two contradictory framings is worth one cheap adjudicator.
  - DEEPEN @ c-crossproc-revocation with fd-security (weight 0.30) — confirmed f-007/f-008 (f-026 upheld). Rationale: highest-risk unconfirmed cluster.
  - FUSE fd-security × fd-performance (weight 0.35) — proposed emergent f-022, **refuted at verify (emergent yield 0).** Rationale: top complementary pair, goal explicitly wants intersection findings.
  - STEER-WIDE → formal-methods (weight 0.15) — produced f-028, the root-cause taste call. Rationale: round-0 novel_cluster_rate 0.67 ≥ 0.6, so widening still paid off; reserved minimal slot.
  - Yield 2 (f-027, f-028), novel_cluster_rate 0.625.
- **Halt: BUDGET.** After round 1, budget.remaining = 2 < round_cost_floor 3 → hard BUDGET halt. (CEILING was also one step away: round would have become 2 = max_rounds.) min_rounds=2 satisfied (rounds 0 and 1).

## If you read one thing

**f-027** (argmax heat = 18): a credential-rotation `purge_all()` does not silently leak the old secret — it crashes every sibling worker with an uncaught `FileNotFoundError` on the next lookup of any warm token, because the index caches the path, not the secret, and nothing re-validates the deleted file. The fix that dissolves it *and* its neighbors is f-028: give the cache one source of truth.

## Caveats discovered during synthesis

- **The fusion produced no surviving emergent finding.** The one it proposed (f-022) inverted the code's actual behavior; the verify gate caught it. This is the loop working as designed, but it means the run's best finding came from PROBE-DISAGREEMENT, not from the named mechanic. On a goal that explicitly asked for intersection findings, the honest answer is "the security × performance intersection is shallower than it looks here."
- **The planted fixture ground-truth (g1) appears to over-claim.** g1 asserts a revoked/purged token "stays live" via the fast path skipping re-validation. Against the literal source, the fast path still reads the file and the index does not cache the secret, so the live-token-survives mechanism does not hold as stated; the real consequence is an availability crash (f-027). Flagged for the fixture author — see the smoke-test report.
- **Budget halted the loop after a single adaptive round.** With --budget=10 and a 3-agent seed, only one round of probes was affordable. A second adaptive round (DEEPEN on the f-027/f-007 disagreement, FUSE of formal-methods × security on the dual-representation root cause) was never reached. Coverage of the store() atomicity region and the umask/secret-at-rest findings was seed-only and unverified.
