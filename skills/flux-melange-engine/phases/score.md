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

Set the halt reason when stopping:
- `round >= max_rounds` → **`CEILING`**
- `budget.remaining < round_cost_floor` → **`BUDGET`** (hard)
- `YIELD <= diminishing_threshold` (and past `min_rounds`) → **`DRY`**

Write `melange-state.json:should_stop` (bool) and `halt_reason`.

## Step 5: GOAL-MET soft stop (`--interactive` only)

If `--interactive` AND the synthesis-so-far would already satisfy `GOAL` (judged by a quick check of the frontier against the goal text), set `should_stop = false` but surface an `AskUserQuestion`: "Goal appears met after round N (frontier: …). Keep spending budget? [Continue / Stop here]". A non-interactive run never prompts — it runs to a hard halt. (Documented follow-up: a `--yes` override could make `goal_satisfied` a hard stop instead of a prompt for unattended runs.)

## Output → the orchestrator

`SKILL.md` reads exactly `should_stop`:
- `false` → re-enter `phases/retarget.md` for round N+1.
- `true` → proceed to `phases/synthesize.md`.

Because every phase only appends findings or stamps status, a crash between rounds leaves a fully replayable ledger — rerunning resumes from the last completed round (see `phases/charter.md` § Resume detection).
