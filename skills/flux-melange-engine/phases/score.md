# Phase 6 — Score + Loop Gate

Close the round: link findings across the whole ledger, measure the round's yield, decrement the budget, and write the single boolean the orchestrator obeys — `should_stop`. This is the only place the loop can end (other than a hard crash), so the predicate here is the control loop's correctness.

## Step 1: Cross-ledger linking

Over the full `heat-ledger.jsonl` (cheap deterministic location pre-filter first, then LLM same-claim judgment only on location-colliding candidates — never quadratic over the whole ledger):

- **`convergence_refs`** — for each finding, the ids of *other* findings in the same `cluster_id` from a **different** lens/tier. High convergence ⇒ high confidence but LOW novelty (commodity). Stamp these refs in.
- **`disagreement_refs`** — ids of findings at the same `location` with a **contradictory** verdict. These seed next round's PROBE-DISAGREEMENT directives.

> Convergence here is exactly flux-review's signal — kept, but reframed: it is a *confidence* annotation, not the rank. The headline is heat (novelty × risk), not agreement.

## Step 2: Measure round yield

```
YIELD = count of findings this round where:
          status == "upheld"
          AND cluster_id is NEW (opened this round, not a duplicate of any prior cluster)
          AND ( novelty >= 2  OR  risk.product >= 6  OR  |taste| >= 2 )
        each weighted by the --weights preset:
          balanced  → equal
          risk-hunt → boost the risk term
          taste     → boost the |taste| term
          novelty   → boost the novelty term
```

Append `{ round, yield, novel_cluster_rate }` to `melange-state.json:gain_history`. Recompute `frontier` (the current top finding ids by heat, for the report).

## Step 3: Decrement budget

`budget.remaining -= (agents dispatched this round: probes + fusions + verifiers + adjudicators)`. Use the **measured** count from the probe/verify phases.

## Step 4: The continue predicate (the loop gate)

```
CONTINUE  ⟺  round < max_rounds                              # not at CEILING
         AND  budget.remaining >= round_cost_floor           # not at BUDGET
         AND  ( round < min_rounds                            # min_rounds guard:
                OR YIELD > diminishing_threshold )            #   never quit on one unlucky round
```

`min_rounds = 2` ensures the loop runs at least twice before yield can stop it — one weak round (e.g. a seed that happened to hit a quiet region) cannot trigger an early DRY halt. `diminishing_threshold` defaults to 1 (a round that opened zero new qualifying clusters is dry).

Set the halt reason when stopping. When more than one condition is true at the same boundary (common: a seed-heavy run hits `BUDGET` on the same round it would hit `CEILING`), record the **first** in this fixed precedence — most-informative-cause first:
1. **`BUDGET`** — `budget.remaining < round_cost_floor` (you ran out of resources; this is what actually stopped you, and it would have stopped you even with more rounds allowed)
2. **`DRY`** — `YIELD <= diminishing_threshold` and past `min_rounds` (the target is exhausted; you stopped by choice, not by limit)
3. **`CEILING`** — `round >= max_rounds` (you hit the configured round cap)

Precedence is BUDGET > DRY > CEILING: a budget exhaustion is the binding constraint, dryness is a quality signal, and the ceiling is the least informative (a mere config cap). Write `melange-state.json:should_stop` (bool) and the single chosen `halt_reason`.

## Step 5: GOAL-MET soft stop (`--interactive` only)

If `--interactive` AND the synthesis-so-far would already satisfy `GOAL` (judged by a quick check of the frontier against the goal text), set `should_stop = false` but surface an `AskUserQuestion`: "Goal appears met after round N (frontier: …). Keep spending budget? [Continue / Stop here]". A non-interactive run never prompts — it runs to a hard halt. (Documented follow-up: a `--yes` override could make `goal_satisfied` a hard stop instead of a prompt for unattended runs.)

## Import-only link mode (Step 2.5 only)

When `skills/flux-melange-engine/SKILL.md` Step 2.5 calls this phase after imported rows have been assayed and verified, run only the import-only link and frontier pass. It **skips** the scorer, convergence, heat, fusion and Taste:

- Do not run `scripts/_melange_score.py`, Step 1 convergence or disagreement stamping, Step 2 yield, Step 3 budget decrement beyond what verify already recorded, Step 4 or Step 5. There is no loop gate here; `should_stop` is not rewritten.
- Do not touch `convergence_refs` or `disagreement_refs` on any row, and do not change any native row's heat, frontier or gain history.
- For each imported row, record in `melange-state.json:import_assimilation` only the ids of native rows in the same cluster (`cluster_id`) as a plain cross-reference, and list import clusters separately from native clusters. An imported row sharing a cluster with a native row does not raise the native row's confidence.
- Round attribution: mark any cluster that holds an imported row as an import cluster in the round attribution of the spice trail, so the report never credits a round or a directive with imported findings.
- Set `import_assimilation.phase` to `link` when this pass starts and `complete` when it finishes, and record `link_dispatches`.

## Output → the orchestrator

`SKILL.md` reads exactly `should_stop`:
- `false` → re-enter `phases/retarget.md` for round N+1.
- `true` → proceed to `phases/synthesize.md`.

Because every phase only appends findings or stamps status, a crash between rounds leaves a fully replayable ledger — rerunning resumes from the last completed round (see `phases/charter.md` § Resume detection).
