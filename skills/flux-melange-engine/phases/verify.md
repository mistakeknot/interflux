# Phase 5 — Verify (Conditional)

A **gated, cheap** verification pass — not a per-round tax. It re-reads the cited locations for only the findings that matter most and stamps `upheld` / `refuted`. This de-defaults the expensive verify-everything path (flagged by the design judges) that would compound cost on a maximize-until-dry goal.

## Gate

Verify fires only on findings where:
```
novelty >= 2  OR  risk.product >= 9
```
(the rare, high-novelty, or high-risk subset — the findings whose truth changes the report). With `--verify=off` the phase is skipped entirely; with `--verify=all` the gate is removed (every raw finding is verified — expensive, for high-stakes targets only).

Findings below the gate keep `status = raw` and are treated as unverified estimates in the loop. Only `upheld` findings count toward `yield` (the DRY-halt signal), so an unverified high-risk finding is a reason to **DEEPEN** next round, not to halt.

## Procedure

For each gated finding, launch a cheap-model `Agent` (haiku/sonnet per `references/budget-ladder.md`) that:
1. Reads the exact cited `location` (`path:lines`) in the real source.
2. Checks whether the `evidence` actually supports the `claim` at that location.
3. Stamps the ledger finding's `status`:
   - **`upheld`** — the artifact confirms the claim.
   - **`refuted`** — the artifact contradicts it (or the location/evidence doesn't exist). Refuted findings stay in the ledger (with `status: refuted`) for the audit trail but are excluded from frontier/yield.

Verifiers may run in parallel; each only reads (no design). Decrement `budget.remaining` by the verifier count.

## Emergent-finding verification

A fusion EMERGENT finding (novelty floored at 3) always clears the gate — the emergence promotion makes it *louder*, so it must be verified *harder*, not trusted. The verifier applies **three** checks in order (the first live run promoted a confident-but-false emergent finding to the top of the report; only this ordering catches it):

1. **Is it true at all?** Re-read the cited `location` in the real source and confirm the claimed mechanism actually exists. A fused lens is *more* prone to a plausible-but-false interaction than a single lens, because it is rewarded for connecting two causes — and "connect two causes" is exactly the shape of a hallucinated link. If the mechanism is not present in the code, stamp **`status: refuted`** (even though novelty was floored at 3 — a refuted finding is excluded from the frontier regardless of its scores). **This is the dominant failure mode; check it first.**
2. **Does it require both parents?** If true, check the `intersection_justification`: could one parent alone have produced it? If one parent suffices, keep `status: upheld` but re-score as non-emergent in synthesis (the guard against fusion degrading into a redundant third reviewer).
3. **Genuine emergent.** True AND requires both parents → `status: upheld`, stays emergent.

Order matters: a refuted finding (check 1) must never reach check 2, or a false interaction gets debated on its merits instead of dropped.

## Output

The ledger's `status` fields are now stamped for the gated subset. Proceed to `phases/score.md`, which links convergence/disagreement across the whole ledger and evaluates the loop gate.
