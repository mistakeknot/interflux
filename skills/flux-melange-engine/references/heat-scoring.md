# Reference: Novelty / Risk / Taste Scoring & the Heat Formula

Three **orthogonal** axes, scored per finding by a dedicated **Assayer** subagent — never the reviewers, who over-rate their own novelty and cannot see what other lenses found. The axes are never collapsed into one number; *derived* ranks (heat, |taste|, fusion-yield) drive surfacing.

## Who scores

One Assayer pass per round sees **all of that round's finding files at once** (so it can judge novelty as *relative* overlap). Model: Sonnet for novelty/risk; the taste annotation is Opus-only (see below). The Assayer reads `findings-helper.sh read-indexes` output (`agent<TAB>finding-line`) to compute overlap deterministically before applying judgment.

## NOVELTY (0–3) — inverse of measured overlap

Novelty is **LLM cluster-matching over a deterministic location pre-filter** — it is *not* a non-LLM metric, and it is *not* read from the `convergence` command (which the source confirms emits only an aggregate tuple and counts P0/P1 only). The Assayer computes overlap itself.

| Score | Meaning |
|-------|---------|
| **0** | Commodity — 3+ agents across 2+ distance tiers found this. Trust it; don't be excited. |
| **1** | 2 agents, same tier. |
| **2** | A single agent in a single domain saw it. |
| **3** | Only *this* lens or fusion could see it — **the spice**. |

**Fusion-emergent findings get a +1 floor** (and the emergence gate may force 3) — see `fusion.md`.

> **Critical decoupling.** Novelty measures a finding's *value*. It does **not** steer the loop. The steering signal is **heat = novelty × risk yield-density** (below). If novelty alone steered, "go toward novelty" + "novelty = unexplored" would manufacture a shallow-novel trickle that never lets the DRY halt fire — the bug the design's judge panel flagged. STEER-WIDE is therefore reserved, not forced.

## RISK = blast_radius × likelihood (product 0–9) — decoupled from severity

This is the class **every ancestor buries.** flux-review ranks on severity + convergence, and its contract maps severity deterministically to verdict — so a P2 rare-catastrophe (blast 3 × likelihood 1 = risk 3) is invisible to it. Melange stores **both** `severity` and `risk.product` and ranks on risk.

| | 0 | 1 | 2 | 3 |
|--|--|--|--|--|
| **blast_radius** | cosmetic / local | one module | several modules / a subsystem | whole system / data / users |
| **likelihood** | requires adversary + luck | rare but plausible | common path under load | already happening / certain |

`risk.product = blast_radius × likelihood`. A blast-3/likelihood-1 (rare catastrophe) and a blast-1/likelihood-3 (constant papercut) both score 3 but mean different things — the Pareto frontier in synthesis keeps them distinct.

## TASTE (−2..+2) — best-effort annotation, NOT a co-equal axis

Demoted (per the classification judge) to a best-effort annotation, scored **only by Opus**, and **only** on findings flagged aesthetic — never billed as co-equal with novelty/risk. It is allowed to be empty for a whole run.

- A reviewer appends `[t]` to its Findings Index line to flag an aesthetic finding; the Assayer also *promotes* findings that argue form over function (elegance, smell) even if unflagged.
- `taste_kind ∈ {elegance, smell, asymmetry, naming, simplicity, metaphor-leak}`.
- `+2` = exemplary, preserve and propagate; `−2` = a smell worth fixing on aesthetic grounds even absent a correctness bug.
- Taste reproducibility is conceded-weak even Opus-only — treat it as a flavor note, not a verdict.

## Clustering (the deterministic pre-filter)

Before any LLM same-claim judgment, the Assayer groups candidate findings by **location overlap**: same file + overlapping line range, or same file + same symbol. Only findings whose locations *collide* are handed to the LLM to decide "same root cause?" This keeps quadratic LLM adjudication off the hot path — the Assayer never asks the model to compare every pair, only the location-colliding ones.

- Findings judged same-root-cause share a `cluster_id`.
- A finding opening a `cluster_id` not seen in any prior round is a **new cluster** (this drives `yield` and `novel_cluster_rate`).

> **Open calibration (documented, not hidden):** the location-overlap threshold is the single load-bearing knob — too loose inflates false convergence (over-halts), too strict never clusters (never-halts). It needs tuning on real runs; start with "same file + overlapping lines OR same file + same top-level symbol" and adjust.

## Derived quantities (computed, not stored as axes)

- **heat** (per finding) = `novelty × risk.product` — the surfacing/steering rank.
- **yield_density** (per region) = sum of `heat` of new-cluster findings in that region ÷ probes spent there. This is what the heat map ranks regions by, and what STEER-WIDE watches for decay.
- **|taste|** — magnitude, for the Taste Calls view (both elegance and smell are interesting).
- **fusion-yield** — emergent findings produced ÷ fusions attempted.
