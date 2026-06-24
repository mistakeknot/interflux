# Measuring & Improving flux-melange

How to tell whether `/flux-melange` is actually good — and how to improve it. This fills the
gap the FluxBench survey flagged: there was no melange-specific measurement methodology, and
the existing FluxBench harness measures the wrong thing for this mode.

## The construct-validity problem (read this first)

FluxBench scores a review by **severity-weighted finding recall** against a gold set
(`P0:4, P1:2, P2:1, P3:0.5`; P0 miss = auto-fail; fuzzy match via Hungarian assignment on
location × description). That is the correct metric for `/flux-drive` and `/flux-review`,
whose job is to find the important bugs ranked by severity.

It is the **wrong** metric for `/flux-melange`, whose entire thesis is that it surfaces what
severity ranking *buries*:

- a **rare catastrophe** — low severity but high `risk = blast_radius × likelihood` (e.g. a
  P2 that fires only during credential rotation but has system-wide blast radius);
- an **elegant fix / taste call** — a P3 whose value is aesthetic (the asymmetry that is the
  root cause of a P0);
- a **fusion-emergent finding** — visible only at the intersection of two lenses, invisible
  to either alone.

If you score melange on severity-weighted recall, you score it on the axis it deliberately
rejects. A melange that does its job *perfectly* can score *worse* than flux-review on
FluxBench recall, because it spends budget chasing high-novelty/high-risk findings instead of
re-confirming the obvious P0 that flux-review's blind fan-out hits for free.

**The metric must match the construct.** Melange's three claimed capabilities → three metrics.

## The three capabilities and their metrics

| Capability (claim) | Metric | Passes when |
|---|---|---|
| **Heat-steering** — round N+1 targeting computed from round N findings beats blind/fixed | **steering lift** = frontier-yield(steered) / frontier-yield(ablated fixed-rotation), same budget/seed/target | lift > 1.0 across ≥3 targets |
| **Lens fusion** — fused lenses surface findings invisible to either parent | **fusion-emergent recall** (did a *fusion* finding match the `requires_fusion` gold finding?) + **negative control** (fusing unrelated lenses yields 0 emergents) | emergent recall > 0 AND negative control = 0 |
| **Novelty/Risk/Taste surfacing** — the report leads with heat, not severity | **frontier recall** + **buried recall** vs a severity-only baseline on the same input; **assayer agreement** (run scores vs gold heat labels) | buried_recall(melange) > buried_recall(flux-review); assayer agreement ≥ 0.6 |

These are computed by `scripts/_melange_score.py` (see below). All are *relative* — the
informative comparison is melange-vs-flux-review or steered-vs-ablated on the **same input**,
not an absolute number.

## The scorer: `scripts/_melange_score.py`

Reuses the FluxBench matcher (`match_score`, `hungarian_maximize`, `MATCH_THRESHOLD` from
`_fluxbench_score.py`) to align a run's findings to a heat-labeled gold set, then computes:
`frontier_recall`, `buried_recall`, `fusion_emergent_recall`, `taste_recall`,
`assayer_agreement` (novelty ±1 & risk.product ±2 vs gold), `false_positive_rate`.

```bash
# Score a melange ledger:
python3 scripts/_melange_score.py \
    docs/research/flux-melange/<slug>/heat-ledger.jsonl \
    tests/fixtures/melange/fixture-token-cache/ground-truth.json

# Score a flux-review run on the SAME gold set (head-to-head):
python3 scripts/_melange_score.py <flux-review-findings.json> <ground-truth.json>
```

Accepts both the melange ledger (`.jsonl`, one finding per line) and a flat
`{"findings":[...]}` JSON (so flux-review output scores against the same gold for head-to-head).

### Demonstrated discrimination (synthetic sanity check)

A "good melange" run (surfaces the planted heat findings, g1 as a fusion finding) vs a
severity-only baseline (only the high-severity findings), both scored against
`fixture-token-cache`:

| Metric | good melange | severity-only baseline |
|---|---|---|
| frontier recall | 1.0 | 0.5 |
| **buried recall** | **1.0** | **0.0** |
| **fusion emergent** | **1.0** | **0.0** |
| **taste surfaced** | **1.0** | **0.0** |
| assayer agreement | 1.0 | 0.5 |

The buried/fusion/taste rows go to **0.0** for severity-only ranking — that is the metric
detecting exactly what melange claims to add and FluxBench cannot see.

## The gold set: `tests/fixtures/melange/`

Extends the FluxBench gold schema (`tests/fixtures/qualification/README.md`) with heat labels
and capability tags. Each finding adds:
`novelty (0-3)`, `risk {blast_radius, likelihood, product}`, `taste (-2..+2)`, `taste_kind`,
`requires_fusion` (+`fusion_parents`), `buried_by_severity`. A top-level
`expected_capability_signals` block names which gold finding is the frontier top, the buried
one, the fusion-emergent one, the taste call, and the commodity controls — plus the
**negative control** (which lens pair must yield zero emergents).

`fixture-token-cache` has deliberately planted structure: a commodity P0 (both modes get it),
a commodity P1 (low novelty), a **fusion-emergent** security×performance bug (a revoked token
stays live because the perf fast-path skips re-validation and purge is process-local), a
**buried-by-severity** P2 (atomicity race that fires on rotation), and a **taste** P3 (the
dual-write asymmetry that is the root cause of the fusion bug). A correct melange run surfaces
the last three in its frontier/fusion/taste views; flux-review buries them by severity.

To add fixtures: clone the dir shape, label heat, and tag the capability signals. Aim for
fixtures whose heat structure is *non-trivial* — a flat severity list with no buried/fusion
structure tests nothing melange-specific.

## Experiment ladder

| # | Experiment | Isolates | Method |
|---|---|---|---|
| E0 | Smoke: run melange once on a real target | does the skill run at all | execute the engine as written; report spec-vs-reality gaps |
| E1 | Head-to-head melange vs flux-review, same fixture | surfacing | compare `frontier_recall` / `buried_recall` |
| E2 | Steered vs fixed-rotation retarget, same budget | heat-steering | `steering lift`; compare `gain_history` decay curves |
| E3 | fusion=auto vs fusion=off + negative control | lens fusion | `fusion_emergent_recall`; negative control = 0 |
| E4 | Assayer scores vs gold heat labels, run ×2 | classification | `assayer_agreement` kappa; taste-score variance across runs |

Run cheapest first; E2/E3 are ablations of E1's run, so build E1 before them.

## Improvement levers (hypotheses, to confirm/refute via experiments)

- **H1 — cross-round cluster matcher threshold** is the single load-bearing knob (drives both
  the convergence signal and the DRY-halt yield count). Too loose ⇒ false convergence ⇒
  over-halt; too strict ⇒ never clusters ⇒ never-halt. E2's `gain_history` reveals which way
  it errs. *Lever:* tune the location-overlap threshold; consider reusing
  `hungarian_maximize` for cross-round matching.
- **H2 — emergence-gate case-3 precision** ("both parents touched the location but neither
  connected the causes" → promote). E3's negative control reveals if it is too loose (it
  should produce zero emergents on an unrelated lens pair). *Lever:* require the gate to read
  both parents' *reasoning*, not just line numbers.
- **H3 — STEER-WIDE reserve starvation** at > 2 directives. E2 at high budget reveals whether
  a dominant DEEPEN/FUSE starves the reserved exploratory probe. *Lever:* the fixed reserve
  floor in `budget-ladder.md`.
- **H4 — taste reproducibility** (conceded weak even Opus-only). E4 run twice measures taste
  variance; if it's noise, demote taste further or drop it from the headline.

## Known interop gaps found during eval (fix candidates)

1. **`claim` vs `description`.** The melange ledger names the finding text `claim`
   (`ledger-schema.md`); the FluxBench matcher keys on `description`. Unmapped, every melange
   finding scores 0 description-similarity and matches nothing. `_melange_score.py` normalizes
   `claim → description` on load. *Consider:* aligning the ledger schema to emit both, or
   teaching `_fluxbench_score.match_score` to fall back to `claim`.

## E0 — first live run: what it proved and what it fixed

The first end-to-end run (`docs/research/flux-melange/eval-token-cache/`, on `fixture-token-cache`)
**ran fully**: seeded, ran one heat-steered adaptive round, fused a lens pair, verified, and
halted correctly on BUDGET. The control loop behaved as designed — the round-1 directives were
demonstrably *computed from* the round-0 ledger (DEEPEN the highest-risk unconfirmed cluster,
FUSE the highest-complementarity non-redundant pair, PROBE-DISAGREEMENT a contradiction,
STEER-WIDE because the novel-cluster rate cleared the gate).

**The headline result is the system catching its own error:** the emergence gate promoted a
confident security×performance interaction to EMERGENT, and the verify step then *refuted* it by
reading the real source. That exposed three real gaps, now fixed:

- **`--budget=auto` was unimplementable** — the spec read a `token_budget` field the estimator
  doesn't emit. Fixed in `budget-ladder.md`: per-agent cost from `estimate-costs.sh`, total
  token budget from `config/flux-drive/budget.yaml` keyed by input type × `max_rounds`, with an
  explicit cold-start fallback.
- **Seed could starve the loop before round 1** — slot accounting conflated cheap *design*
  passes with *review* probes. Fixed in `seed.md`: a slot counts a review probe (≈2 for the
  seed), not the design pass; plus a budget-aware shrink when `total < 6`.
- **No verify branch for "the emergent finding is simply wrong"** — the gate could amplify a
  hallucinated interaction to the headline. Fixed in `verify.md`: emergent verification now
  checks *is-it-true-at-all* FIRST (refute on absence), before the requires-both-parents check.
  A fused lens is *more* prone to plausible-but-false links, so promotion demands harder, not
  softer, verification.
- Minor: `score.md` now defines halt precedence (BUDGET > DRY > CEILING) for coincident halts.

It also caught a bug in **this gold set**: the planted fusion finding (g1) originally over-claimed
a mechanism the fixture code didn't have. Both the fixture code and g1 were corrected so the
security×performance interaction is genuinely present (the index caches the *secret* and lookup
never reads the file, so a purged credential survives in other processes' indices). Lesson: run
the system before trusting the harness built around it — a gold set that asserts a false finding
silently penalizes every correct run.

**Still open (no script support, done by hand in E0):** `score.md`'s cross-ledger
`convergence_refs` linking has no tooling — `findings-helper.sh convergence` emits only an
aggregate P0/P1 tuple, not per-finding refs. A small helper that emits per-finding
location-overlap pairs (reusing `hungarian_maximize`) would close this; until then the linking is
manual LLM work, which is fine for small runs but won't scale.

## E1 — head-to-head: melange vs flux-review (first real measurement)

Both arms blind to ground truth. Baseline = a 3-lens severity-ranked single pass (faithful
flux-review emulation). Melange = the E0 live ledger.

| metric | flux-review baseline | flux-melange E0 |
|---|---|---|
| matched / 5 gold | 2 | **4** |
| frontier recall | 0.5 | **1.0** |
| assayer agreement | 0.0 (no heat scores) | **0.75** |
| buried recall | 1.0 | 1.0 (tie) |
| fusion emergent | 0.0 | 0.0 |

**Supports the central claim:** melange matched twice as many planted findings and got both
Pareto-front findings, and its heat scores genuinely track the gold labels (0.75 agreement). On
"surface the high-heat findings," melange beat the severity baseline.

**But E1's most valuable output was three measurement bugs it exposed** — a reminder that you
must run the system before trusting the harness:

1. **Score the surfaced set, not the raw ledger.** Scoring all 29 ledger rows (incl. raw/refuted/
   convergent duplicates) against 5 gold findings forced a false-positive rate of 0.86 — an
   artifact, not a melange flaw. *Fix:* `_melange_score.py --surfaced` + the synthesis now emits
   `surfaced.jsonl` (see `synthesize.md`).
2. **A single Pareto front is the wrong "surfaced" definition.** It discards the buried finding
   (surfaced via the report's *risk axis* / "if you read one thing") and the taste call (the
   *Taste* view). The surfaced set is the **union of the five synthesis views**, not one front —
   which is exactly why the engine must *declare* it (`surfaced.jsonl`) rather than have the
   scorer guess. The `--surfaced` flag's heuristic union is a coarse fallback for ledgers
   predating that contract; it intentionally errs on the buried finding (no threshold rule can
   place a high-blast/low-likelihood finding correctly — that is the construct).
3. **Recall hides the burying; rank is the construct.** The baseline *found* the buried finding
   (recall 1.0) but ranked it P2 below the P0/P1s — the whole point. A recall metric can't see
   that. *Open lever:* a rank-aware metric (position of the buried finding in melange's frontier
   vs its severity rank in the baseline). Not yet built — flagged for the next pass.

**Methodological note (when to STOP tuning):** after these fixes, further adjustment of the
`--surfaced` fallback threshold was chasing the fixture's single hardest finding. The sound fix
is the `surfaced.jsonl` contract (done) validated by a *fresh* run that emits it — not retrofitting
a heuristic onto the E0 ledger. E2–E4 (steering ablation, fusion ablation + negative control,
assayer kappa across runs) should run against a fresh corrected-fixture run that emits
`surfaced.jsonl`.
