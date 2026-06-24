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

A fusion EMERGENT finding (novelty floored at 3) always clears the gate. Its verifier additionally checks the **`intersection_justification`**: does the finding genuinely require both parents, or could one parent alone have produced it? If one parent suffices, demote it (`status: upheld` but re-scored as non-emergent in synthesis) — this is the guard against fusion degrading into a redundant third reviewer.

## Output

The ledger's `status` fields are now stamped for the gated subset. Proceed to `phases/score.md`, which links convergence/disagreement across the whole ledger and evaluates the loop gate.
