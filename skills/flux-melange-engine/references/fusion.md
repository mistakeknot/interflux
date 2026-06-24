# Reference: Lens Fusion

Fusion is the mechanic the mode is named for: two review lenses become a **third** hybrid lens that reports *only* findings invisible to either parent alone. flux-review's convergence detects when independent lenses *agree*; fusion detects what lives at their *intersection* — the productive disagreement.

## The Lens Record (makes fusion mechanical, not vibes)

Every agent that runs — base or fused — gets one **lens record**, written to `lenses/{agent}.json` by the seed synthesis and refreshed by the assay step:

```json
{
  "id": "fd-migration-atomicity",
  "kind": "base",
  "parents": [],
  "domain": "database migration / transaction safety",
  "axioms": [
    "Every multi-statement change must be atomic or have a defined partial-failure state",
    "A constraint added after a backfill assumes the backfill cannot be interrupted",
    "Rollback must restore an equivalent pre-state, not merely undo the last statement"
  ],
  "primitives": ["transactions", "constraints", "backfill ordering", "lock duration"],
  "failure_mode": ["ignores read-side latency", "ignores cross-service ordering", "ignores UX of downtime"],
  "findings": ["f-007", "f-014"]
}
```

`axioms` (3–7 load-bearing assumptions), `primitives` (the units it reasons about), and `failure_mode` (what it *systematically misses*) are filled by a one-shot pass over the agent's system prompt + its *actual* findings. The triple is what converts "fuse two lenses" from theater into a deterministic, evidence-grounded operator.

## Candidate selection (trimmed to the two terms that carry signal)

The judge panel cut a decorative four-term score. The kept formula over unordered pairs of already-run lenses:

```
fusion_score(A, B) = SHARED_HEAT(A, B) + COMPLEMENTARITY(A, B) − REDUNDANCY(A, B)
```

- **SHARED_HEAT** — both lenses fired findings on the same file / section / line-range. The strongest evidence a hidden interaction lives there. **Hard gate:** a pair must clear a SHARED_HEAT threshold to be eligible at all — we never fuse two lenses that merely agree in the abstract or never touched the same ground.
- **COMPLEMENTARITY** — one lens's `primitives` fall inside the other's `failure_mode` (each sees the other's blind spot). Computed from the lens records.
- **REDUNDANCY** — penalty for pairs that already *co-converged* on the same `cluster_id`. Fusing agreers yields nothing; this kills those pairs.

Pick top-K (K = fusion budget, default ≤ 2 per round). `interlens` MCP tools (`combine_lenses`, `find_contrasting_lenses`) **seed** candidate pairs and a named synthesizing third lens when available; the controller heuristics above are the fallback — an accelerant, not a dependency.

## The hybrid-lens charter

A fused lens is a single synthetic `fd-*` agent spec, built at runtime through the **same** validated `generate-agents.py --from-specs … --json` path (so it is a first-class reviewable object, not a special case), with `parent_lenses` recorded. Spec saved to `.claude/flux-gen-specs/{SLUG}-fusion-{k}.json`.

Charter template (the `persona` / `decision_lens` / `review_areas` are built from the intersection):

```
You are a fused review lens combining two perspectives:
  PARENT A — {A.domain}: axioms {A.axioms}; reasons about {A.primitives}.
  PARENT B — {B.domain}: axioms {B.axioms}; reasons about {B.primitives}.

These parents CONTRADICT on: {the tension — name it}. Do NOT resolve the
contradiction. INVESTIGATE the places where it lives.

Your fused primitive is the cross-product, e.g.:
  security × performance → "every place a security control sits on a hot path,
  where a team would quietly weaken it for latency."

HARD CONSTRAINT: report a finding ONLY if it requires BOTH parent perspectives.
If either parent ALONE would catch it, discard it. Every finding must include an
`intersection_justification`: one sentence naming what each parent contributes
and why neither alone suffices.
```

## The emergence gate (folded into the assay step)

After a fused probe runs, the gate checks each fused finding's `location` against **both** parents' Findings Indexes:

1. **A parent already reported that location + root cause** → **demote** to convergence (still valuable — high confidence — but not emergent; novelty falls to the normal scale).
2. **Neither parent touched the location** → **promote** to EMERGENT (novelty floored at 3), tag the parent pair.
3. **Both parents touched the location but neither CONNECTED the two causes** → **promote** to EMERGENT — this is the real prize: the interaction only the fused lens can name.

Case 3 is a harder semantic judgment than a line-check (the documented open question on whether fusion is a genuine interaction-detector or degrades into a redundant third reviewer). The gate must read both parents' *reasoning*, not just their line numbers — if either parent's finding at that location already articulates the causal link, demote.

**Zero-emergent fusions are reported as negative results** ("security × i18n: independent here") and **steer the next round AWAY from that region** — a fusion that finds nothing is itself information.

## Depth

- **Depth-1** (fusing two base lenses) is the default.
- **Depth-2** (fusing a fused lens with another lens) is allowed **only on `--quality=max`**. No unbounded fusion-of-fusion compounding — the judges flagged it as a complexity sink with no demonstrated payoff.
