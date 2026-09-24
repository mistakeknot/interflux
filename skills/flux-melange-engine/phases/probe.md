# Phase 4 — Probe

Run the round's directives as parallel background reviews. Each directive becomes one or more `Agent` calls; each gets its **own** output dir so concurrent probes on the same `INPUT_PATH` never clobber.

## Output isolation (mandatory — the "issue #6" trick)

Every probe in a round reviews the same `INPUT_PATH`, so without explicit dirs they would content-address to the identical default and race. Assign:
```
OUTPUT_ROOT/round-N/probe-{k}/        # k = directive index within the round
```
Give this directory directly to the restricted worker in its prompt. Each
reviewer writes a different findings path, so concurrent probes cannot clobber
one another.

## Dispatch per directive type

Launch all probes for the round in parallel (`run_in_background: true`), respecting the per-directive agent counts from `phases/retarget.md`. Use the prompt template **verbatim** — do not add strategic-influence framing (it can trip server-side input classifiers). Inject `GOAL` as the north star in every prompt.

Create each output dir with `mkdir -p` in the orchestrator before dispatch.
Dispatch each reviewer directly as `Agent` with
`subagent_type: interflux:melange-worker`; this agent can read source and use
guarded Write/Edit tools, but has no shell, skill, or external-runtime tools.
Pass the probe model from `references/budget-ladder.md` on each Agent call.
Do not nest a review skill inside the probe. Read the selected lens record or
generated lens file and include its axioms and focus in the direct prompt.

For every directive, the reviewer must use Write to create
`{OUTPUT_ROOT}/round-N/probe-{k}/{lens_id}.md` with a standard Findings Index,
Verdict, Summary, Issues Found, and Improvements. Use this shape:
```
### Findings Index
- P1 | L1 | "path:line" | Concrete claim
Verdict: safe|needs-changes|risky

### Summary
...

### Issues Found
L1. P1: Concrete claim — evidence at path:line.

### Improvements
...
```
`L1` is local to this file; the Assayer assigns globally unique `f-NNN` IDs in
the ledger. An empty index with `Verdict: safe` represents no findings. Return
the output path and finding count to the orchestrator. Do not write a temporary findings
file and do not invoke a helper or subprocess to produce the report.

Every probe prompt additionally carries (mk-8wk):
- **Settled facts** — up to 10 upheld claims from earlier rounds (heat-ordered, one line each) under "SETTLED FACTS — do NOT re-litigate, re-confirm, or spend findings on these; build on them". This is the loop's working memory; without it later rounds re-pay for what verify already settled.
- **Remediation channel** — instruct: if a verdict implies amending the REVIEW TARGET/BRIEF itself (a settled fact the brief contradicts, a framing to drop, a question to add), state it as ONE imperative sentence in the finding's `remediation` field (distinct from `suggestion`, which stays for ordinary code/design fixes). Remediations are routed to the report's `prescriptions` — the loop never edits its own target.
- **Artifact safety** — findings Markdown goes through Write in the restricted
  melange worker.

**DEEPEN / PROBE-DISAGREEMENT** — a single-lens review at a specific location:
```
Run a focused review of {INPUT_PATH} at {target.location} through the lens {lens}.
Use the supplied lens axioms and write to {OUTPUT_ROOT}/round-N/probe-{k}/{lens_id}.md.
Goal (north star): {GOAL}.
You are CONFIRMING OR REFUTING this prior finding: "{finding.claim}" ({finding.location}).
For PROBE-DISAGREEMENT: adjudicate the contradiction between {f1.claim} and {f2.claim} —
decide which holds, or whether it is an irreducible taste call (elegant vs reckless).
Write a standard Findings Index + verdict. Append [t] to any aesthetic finding line.
```

**FUSE** — a review through the synthetic hybrid lens:
```
Run a review of {INPUT_PATH} through the FUSED lens {fusion_agent}
(parents: {A}, {B}). Write to {OUTPUT_ROOT}/round-N/probe-{k}/{fusion_agent}.md.
Goal (north star): {GOAL}.
HARD CONSTRAINT (already in the fused agent's charter): report a finding ONLY if it
requires BOTH parent perspectives; if either parent alone would catch it, discard it.
Every finding MUST include an intersection_justification.
Write a standard Findings Index + verdict.
```

**STEER-WIDE** — a direct review through the new distant lens at its isolated output dir, goal-biased.

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
