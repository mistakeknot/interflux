# Phase 3 — Retarget (the Controller)

The controller is a **pure function over the ledger**: read the scored findings → compute the heat map → emit 2–4 typed directives for the next round. This is the closed loop's hinge — the thing no ancestor has. Given the same ledger, it produces the same directives (modulo the LLM lens-design inside FUSE/STEER-WIDE).

This phase is deterministic enough to run **inline** (no subagent) — it is arithmetic over JSON plus a small selection policy. Spawn subagents only for the lens *design* that FUSE and STEER-WIDE require.

## Step 1: Compute the heat map

From the full `heat-ledger.jsonl`, compute and write `melange-state.json:heat_map`:

- **`regions[]`** — group findings by file/section. For each: `yield_density` = Σ `heat` of *new-cluster* findings ÷ probes spent there (see `references/heat-scoring.md`); `max_risk`; `disagreement_flags` count. Rank descending by `yield_density`.
- **`lens_pairs[]`** — for every unordered pair of run lenses, compute `SHARED_HEAT`, `COMPLEMENTARITY`, `REDUNDANCY`, `score = shared_heat + complementarity − redundancy` (`references/fusion.md`). Keep only pairs above the SHARED_HEAT gate. Rank by score.
- **`disagreement_flags[]`** — locations where two findings have opposite verdicts (same `location`, contradictory claims). Carry their `finding_ids`.

Also recompute `gain_history` for the last round: `yield` (count of verified, new-cluster findings meeting the `--weights`-boosted threshold) and `novel_cluster_rate` (new clusters ÷ total findings this round).

## Step 2: Select directives (the policy)

Apply the selection priority from `references/directive-vocabulary.md`, filtered by the `GOAL` as a relevance test ("does pursuing this directive serve the stated goal?"):

1. **PROBE-DISAGREEMENT** for each open high-value `disagreement_flag`.
2. **DEEPEN** the top unconfirmed high-risk clusters (`risk.product` high, `convergence_refs == []`, `status != upheld`) — subject to the **settled-cluster gate** (mk-8wk, see directive-vocabulary.md): skip clusters already DEEPENed this run and clusters whose locations overlap a settled (upheld) region; log the cids the gate closes.
3. **FUSE** the top non-redundant lens pairs above the SHARED_HEAT gate (≤ fusion budget; depth-2 only on `--quality=max`).
4. **STEER-WIDE** *iff* last round's `novel_cluster_rate ≥ wide_threshold` (default 0.6) — else **skip and reallocate its weight**.

Cap at 2–4 directives total. Assign `budget_weight`s summing to ≤ 1.0, biased toward higher-heat directives. Scale into agent counts per `references/budget-ladder.md` (reserve a floor for an active STEER-WIDE so it is not starved).

## Step 3: Generate the lenses each directive needs

- **DEEPEN / PROBE-DISAGREEMENT** typically reuse an existing adjacent lens (named in the directive) — no design needed.
- **FUSE** builds a synthetic fused-lens spec from the two parents' lens records (`references/fusion.md` § charter), saved to `.claude/flux-gen-specs/{SLUG}-fusion-{k}.json` and generated via `generate-agents.py --from-specs`. Use `interlens combine_lenses` to seed the hybrid when available.
- **STEER-WIDE** designs a new distant/esoteric lens from a domain maximally distant from `coverage.regions`/`tiers_used` (reuse the flux-explore distant prompt with the accumulated-coverage list), goal-biased.

## Output

Write `OUTPUT_ROOT/round-N-directives.json` (array of directive objects, schema in `references/directive-vocabulary.md`) and the updated `melange-state.json` (with the fresh `heat_map`, `gain_history`, `coverage`). Proceed to `phases/probe.md`.

## Worked behavior

See `references/directive-vocabulary.md` § Worked example — the canonical demonstration that the round's *shape* is computed from findings, not fixed up front. That is the entire point of the mode.
