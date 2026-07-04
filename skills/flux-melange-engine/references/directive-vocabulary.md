# Reference: Directive Vocabulary

The controller (`phases/retarget.md`) reads the ledger and emits 2–4 **typed directives** for the next round. This typed vocabulary is the real escalation over the ladder: `flux-review` triages distance *once* and runs blind; `flux-explore` only ever goes *further out* (monotonic, away from coverage). A directive lets compute move **toward** heat or **away** from it, decided per-directive from the prior round's heat map.

Each directive in `round-N-directives.json`:

```json
{
  "type": "DEEPEN",
  "target": { "region": "migrations/0042_add_account_id.sql:14-31", "cluster_id": "c-backfill-ordering" },
  "rationale": "f-007 (risk 4, novelty 2) found once, unconfirmed — confirm or refute before it leads the report.",
  "lens": "fd-rollback-safety",
  "budget_weight": 0.35
}
```

## The four directive types

### DEEPEN — toward an unconfirmed hotspot
Spawn an adjacent lens at the **exact location** of a high-risk, low-convergence cluster (found once, scary, unconfirmed) to confirm or refute it.
- **Fires when:** a cluster has high `risk.product` but `convergence_refs == []` and `status != upheld`.
- **Effect:** narrows compute onto a known-hot point. The opposite of flux-explore's outward drift.

### FUSE — toward a lens intersection
Construct a fused lens from the two hottest non-redundant lenses (per `fusion.md`) and probe their intersection.
- **Fires when:** `heat_map.lens_pairs` has a pair above the SHARED_HEAT gate with positive `fusion_score`.
- **Effect:** the melange move — manufacture a new lens rather than reuse existing ones. Capped at the fusion budget (≤ 2/round; depth-2 only on `--quality=max`).

### STEER-WIDE — away, toward novel ground (RESERVED)
flux-explore's distant jump, but goal-biased: generate a lens from a domain maximally distant from current coverage.
- **Fires only while** `novel_cluster_rate` stays above the wide threshold — i.e. while widening is still *paying off*.
- **RESERVED, not forced every round.** This is the deliberate fix for the design's self-defeating-loop flaw: a forced wildcard every round manufactures a shallow-novel trickle that defeats the DRY halt. STEER-WIDE earns its slot by recent novel-cluster productivity; otherwise the budget goes to DEEPEN/FUSE.

### PROBE-DISAGREEMENT — toward a contradiction
Spawn an adjudicator on any `disagreement_flag` (two findings, same location, opposite verdict — often a taste call: *elegant* or *reckless?*).
- **Fires when:** `heat_map.disagreement_flags` is non-empty.
- **Effect:** resolves (or sharpens) a live contradiction. flux-review discards non-convergent contradictions as noise; melange treats them as primary signal.

## Selection policy (the controller as a pure function)

Given the heat map and budget, the controller picks 2–4 directives by this priority, subject to budget weights:

1. **PROBE-DISAGREEMENT** for every open `disagreement_flag` whose findings include a high-risk or aesthetic claim (cheap, high-value — resolves ambiguity).
2. **DEEPEN** the top unconfirmed high-risk clusters (confirm the scary-but-unverified before it can lead the report).
3. **FUSE** the top non-redundant lens pairs above the SHARED_HEAT gate.
4. **STEER-WIDE** *iff* `novel_cluster_rate` (last round) ≥ the wide threshold — else skip and reallocate.

`budget_weight`s sum to ≤ 1.0 and are scaled into agent counts by `budget-ladder.md`. The controller is deterministic given the ledger: same ledger → same directives (modulo the LLM lens-design step inside FUSE/STEER-WIDE).

## Worked example (round 1 → round 2)

Round 1 left: a high-risk unconfirmed backfill cluster (`f-007`), a hot lens pair (`fd-migration-atomicity` × `fd-supply-chain-flow`, shared_heat 3), one disagreement at `cache.go:88`, and `novel_cluster_rate` down to 0.55.

Controller emits:
- `PROBE-DISAGREEMENT` @ `cache.go:88` (weight 0.20)
- `DEEPEN` @ backfill cluster with `fd-rollback-safety` (weight 0.35)
- `FUSE` migration × supply-chain (weight 0.30)
- `STEER-WIDE` *skipped* — 0.55 is below the 0.6 wide threshold; its 0.15 reallocates to DEEPEN.

This is the behavior no ancestor can produce: the round's shape is *computed from the findings*, not fixed up front.
