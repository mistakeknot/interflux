# Phase 7 — Synthesize (the Eye of Distance)

One Opus agent reads the **full** ledger and produces a **surfacing-first** report — never a flat severity list. It re-scores the merged ledger (the per-round assayer scores were triage-grade; these are the trustworthy numbers) and emits five views plus a spice-trail appendix.

## Launch

Model: Opus on `balanced`/`max`, Sonnet on `economy`. Input: the entire `heat-ledger.jsonl`, `melange-state.json`, all `round-N-directives.json`, and `lenses/`.

Prompt template (verbatim):
```
You are writing the synthesis for a flux-melange spice-loop review — the eye of distance.

Target: {TARGET_DESC}    File: {INPUT_PATH}
Goal: {GOAL}    Weights: {WEIGHTS}
The loop ran {rounds} rounds and halted: {halt_reason}.

Here is the full heat ledger (every finding, scored on novelty/risk/taste, with
cluster/convergence/disagreement links and status), the per-round directives, and
the lens records:
{ledger + directives + lens records}

First, RE-SCORE the merged ledger yourself — the per-round scores were fast triage
estimates. Then produce these five views (surface the spice; do NOT sort by severity):

## 1. Novelty×Risk Frontier
The Pareto FRONT (not a single sort) of upheld findings on (novelty, risk.product):
surface a max-novelty/mid-risk finding AND a mid-novelty/max-risk finding — both
lead. For each: the claim, lens(es), the risk decomposition (blast × likelihood),
and severity FOR REFERENCE ONLY. This is where a rare-catastrophe (blast 3 ×
likelihood 1) every ancestor buries finally surfaces.

## 2. Top Fusions
Emergent findings no single lens could produce — the section this mode exists for.
Rank by novelty×risk. For each: the parent pair, the intersection_justification,
and the evidence. Report zero-emergent fusions as negative results ("A × B:
independent here").

## 3. Taste Calls
Top +taste elegance to preserve and top -taste smells to fix (Opus annotation; may
be empty). Name the taste_kind.

## 4. Convergence Spine
flux-review's signal, KEPT but DEMOTED: high-convergence findings = high confidence,
LOW novelty (commodity you can trust). One section, not the headline.

## 5. Live Disagreements
Contradictions still open at halt — flux-review discards these as non-convergent
noise; here they are primary signal (often unresolved taste calls: elegant vs reckless).

Then an appendix:

## Spice Trail
Per round: yield, novel_cluster_rate, the directives chosen and WHY (the rationale),
what steered where, and the halt reason. This is the audit trail of how the loop moved.

Optionally, a single "If you read one thing" = argmax(heat), |taste| as tiebreaker.

Write in direct technical prose. Name agents/lenses when attributing. Rank by HEAT
(novelty × risk), never by severity alone.
```

## Output

Write to `{OUTPUT_ROOT}/{DATE}-synthesis.md` with frontmatter:
```yaml
---
artifact_type: melange-synthesis
method: flux-melange
target: "{INPUT_PATH}"
target_description: "{TARGET_DESC}"
goal: "{GOAL}"
weights: {WEIGHTS}
rounds_run: {N}
halt_reason: {DRY | BUDGET | CEILING | GOAL-MET}
total_fusions: {attempted}
emergent_findings: {count of EMERGENT findings}
date: {DATE}
---
```

Include any caveats discovered during synthesis (a probe that failed and contributed no findings; a fusion that produced only redundant findings; a region the loop never reached before halting on budget).

## Then → Phase 8 Report

Return to `SKILL.md` § Report to print the paths, spice trail, halt reason, total cost, and regeneration hints.
