# Reference: Heat Ledger & State Schema

The **heat ledger** is the single threaded state object that makes the loop closed. Everything the controller decides is a pure function of it. It lives at `{PROJECT_ROOT}/docs/research/flux-melange/{SLUG}/`.

## `heat-ledger.jsonl` — append-only, one JSON object per finding

```json
{
  "id": "f-007",
  "round": 2,
  "source": {
    "kind": "lens",
    "agents": ["fd-migration-atomicity"],
    "parent_lenses": [],
    "source_domains": ["database migration"]
  },
  "claim": "Backfill runs before the NOT NULL constraint is added, so a crash mid-backfill leaves rows the constraint will later reject.",
  "location": "migrations/0042_add_account_id.sql:14-31",
  "severity": "P1",
  "novelty": 2,
  "risk": { "blast_radius": 2, "likelihood": 2, "product": 4 },
  "taste": 0,
  "taste_kind": null,
  "cluster_id": "c-backfill-ordering",
  "convergence_refs": [],
  "disagreement_refs": [],
  "intersection_justification": null,
  "evidence": "migration applies constraint at L31 after the UPDATE at L14; no transaction wraps both.",
  "status": "upheld"
}
```

Field contract:

| Field | Type | Written by | Notes |
|-------|------|-----------|-------|
| `id` | string | reviewer/probe | `f-NNN`, monotonic across the whole run |
| `round` | int | probe | 0 = seed |
| `source.kind` | `lens` \| `fusion` | probe | `fusion` ⇒ `parent_lenses` non-empty |
| `source.agents` | string[] | probe | the `fd-*` agent(s) that reported it |
| `source.parent_lenses` | string[] | probe | for fused lenses, the two parent agent ids |
| `source.source_domains` | string[] | probe | distance-tier provenance |
| `claim` | string | reviewer | the finding, one sentence |
| `location` | string | reviewer | `path:line` or `path:start-end` — **load-bearing**: the dedup/convergence pre-filter keys on this |
| `severity` | `P0`..`P3` | reviewer | kept for reference; **not** the rank |
| `novelty` | 0–3 | **assayer** | see `heat-scoring.md`; fusion-emergent floored at 3 |
| `risk.blast_radius` | 0–3 | **assayer** | how far damage spreads |
| `risk.likelihood` | 0–3 | **assayer** | how likely to fire |
| `risk.product` | 0–9 | **assayer** | `blast_radius × likelihood`, decoupled from severity |
| `taste` | −2..+2 | **assayer (Opus only)** | best-effort annotation; may be 0/empty |
| `taste_kind` | enum\|null | assayer | `elegance` \| `smell` \| `asymmetry` \| `naming` \| `simplicity` \| `metaphor-leak` |
| `cluster_id` | string | assayer | findings sharing a root cause share a cluster |
| `convergence_refs` | string[] | score phase | ids of other findings in the same cluster from *different* lenses/tiers |
| `disagreement_refs` | string[] | score phase | ids of findings that *contradict* this one (same location, opposite verdict) |
| `intersection_justification` | string\|null | fused probe | required for `fusion` findings; why BOTH parents were needed |
| `evidence` | string | reviewer | the concrete artifact citation backing the claim |
| `remediation` | string (optional) | reviewer | ONE imperative sentence amending the review TARGET/BRIEF itself (mk-8wk) — routed to the report's `prescriptions`; distinct from `suggestion` (ordinary fix) |
| `status` | `raw` \| `upheld` \| `refuted` | verify phase | `raw` until verified or below the verify threshold |

## `melange-state.json` — rewritten each round (the controller's working memory)

```json
{
  "objective": "maximize verified novelty×risk surface until dry",
  "weights": "balanced",
  "round": 2,
  "min_rounds": 2,
  "max_rounds": 4,
  "budget": { "total": 30, "remaining": 17, "round_cost_floor": 4 },
  "coverage": {
    "regions": ["migrations/", "internal/store/"],
    "tiers_used": ["adjacent", "distant"],
    "lens_pairs_fused": [["fd-migration-atomicity", "fd-supply-chain-flow"]]
  },
  "heat_map": {
    "regions": [
      { "region": "migrations/0042_add_account_id.sql", "yield_density": 2.5, "max_risk": 6, "disagreement_flags": 0 }
    ],
    "lens_pairs": [
      { "pair": ["fd-migration-atomicity", "fd-rollback-safety"], "shared_heat": 3, "complementarity": 2, "redundancy": 0, "score": 5 }
    ],
    "disagreement_flags": [
      { "location": "internal/store/cache.go:88", "finding_ids": ["f-011", "f-012"] }
    ]
  },
  "gain_history": [
    { "round": 0, "yield": 9, "novel_cluster_rate": 1.0 },
    { "round": 1, "yield": 5, "novel_cluster_rate": 0.55 },
    { "round": 2, "yield": 2, "novel_cluster_rate": 0.22 }
  ],
  "frontier": ["f-007", "f-003", "f-019"],
  "should_stop": false,
  "halt_reason": null
}
```

`should_stop` and `halt_reason` are written by the **loop gate** (`phases/score.md`). The orchestrator reads exactly these two fields to decide whether to re-enter `phases/retarget.md`.

## Per-round side artifacts

- `round-N-directives.json` — the controller's output for round N (see `directive-vocabulary.md`).
- `lenses/` — one **lens record** per agent that has run (see `fusion.md` for the shape; produced by the seed-synthesis and assay passes).
- `round-N/probe-k/` — per-probe flux-drive-style output dirs (Findings Index + verdict), kept disjoint by explicit `--output-dir`.

## Invariants

1. **Append-or-stamp only.** Findings are never edited after write; only `status`, `convergence_refs`, `disagreement_refs`, and the assayer's score fields are stamped in. This is what makes the ledger replayable after a crash.
2. **Location is the join key.** Cross-round clustering, convergence, disagreement, and the fusion emergence gate all key on `location` via a deterministic prefix/overlap match *before* any LLM judgment runs (see `heat-scoring.md` § Clustering). This keeps per-round LLM adjudication off the quadratic path.
3. **Scores are triage-grade during the loop, trustworthy at synthesis.** Per-round assayer scores steer the loop; the synthesis agent re-scores the merged ledger for the report. Treat in-loop scores as fast estimates.
