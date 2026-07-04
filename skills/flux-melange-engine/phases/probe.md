# Phase 4 — Probe

Run the round's directives as parallel background reviews. Each directive becomes one or more `Agent` calls; each gets its **own** output dir so concurrent probes on the same `INPUT_PATH` never clobber.

## Output isolation (mandatory — the "issue #6" trick)

Every probe in a round reviews the same `INPUT_PATH`, so without explicit dirs they would content-address to the identical default and race. Assign:
```
OUTPUT_ROOT/round-N/probe-{k}/        # k = directive index within the round
```
Pass this as the review's `--output-dir`. This mirrors how `flux-review-engine/phases/track-dispatch.md` keeps tracks disjoint.

## Dispatch per directive type

Launch all probes for the round in parallel (`run_in_background: true`), respecting the per-directive agent counts from `phases/retarget.md`. Use the prompt template **verbatim** — do not add strategic-influence framing (it can trip server-side input classifiers). Inject `GOAL` as the north star in every prompt.

**DEEPEN / PROBE-DISAGREEMENT** — a single-lens review at a specific location:
```
Run a focused review of {INPUT_PATH} at {target.location} through the lens {lens}.
Use the `interflux:flux-engine` skill with --output-dir {OUTPUT_ROOT}/round-N/probe-{k}.
Goal (north star): {GOAL}.
You are CONFIRMING OR REFUTING this prior finding: "{finding.claim}" ({finding.location}).
For PROBE-DISAGREEMENT: adjudicate the contradiction between {f1.claim} and {f2.claim} —
decide which holds, or whether it is an irreducible taste call (elegant vs reckless).
Write a standard Findings Index + verdict. Append [t] to any aesthetic finding line.
```

**FUSE** — a review through the synthetic hybrid lens:
```
Run a review of {INPUT_PATH} through the FUSED lens {fusion_agent}
(parents: {A}, {B}). Use the `interflux:flux-engine` skill with
--output-dir {OUTPUT_ROOT}/round-N/probe-{k}.
Goal (north star): {GOAL}.
HARD CONSTRAINT (already in the fused agent's charter): report a finding ONLY if it
requires BOTH parent perspectives; if either parent alone would catch it, discard it.
Every finding MUST include an intersection_justification.
Write a standard Findings Index + verdict.
```

**STEER-WIDE** — a review through the new distant lens (standard flux-engine review at its output dir, goal-biased).

## After all probes complete

Display per-directive results:
```
✓ round N probe-0 (DEEPEN @ {loc}): {n} findings
✓ round N probe-1 (FUSE {A}×{B}): {n} findings ({emergent} candidate-emergent)
✓ round N probe-2 (PROBE-DISAGREEMENT @ {loc}): resolved {verdict}
[STEER-WIDE skipped — novel_cluster_rate below threshold]
```

Decrement `melange-state.json:budget.remaining` by the **actual** number of agents dispatched (not an estimate). Proceed to `phases/verify.md`.

## Graceful degradation

If a probe fails (timeout, error), drop that directive's findings and proceed with the survivors — the round still contributes. Note the failure in the round's spice-trail entry so synthesis can report it. A failed FUSE is recorded as "no result" (distinct from a zero-emergent fusion, which is a real negative result that steers away from that region).
