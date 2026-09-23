# Phase 1 — First Taste (Round 0)

The **only** round not steered by heat. Its job is to populate the ledger with first findings, the lens records that fusion and retargeting depend on, and the initial heat map — so round 1's controller has something to be a pure function *of*.

## Design the seed lenses (2 tiers, compact)

Seed deliberately mirrors `flux-review`'s two outer tiers — **adjacent** (domain experts) + **distant** (cross-domain isomorphisms) — not the full 4-track lattice. Two tiers give the controller both a "deep" and a "wide" starting signal without spending the budget before the loop begins.

> **Slot accounting (clarified — this tripped the first live run).** A *slot* counts a **review/probe agent** that consumes context against the target, not the cheap design pass that *writes* the lens specs. Two design subagents (one per tier) produce N lens specs in one shot; generating them costs design tokens, not slots. The slots the seed spends are the **review probes** — by default 2 (one adjacent review, one distant review), regardless of how many lens specs were designed. So a 10-slot budget spends ~2 on the seed and leaves ~8 for the adaptive rounds, consistent with the "2-round economy ≈ 8–10 slots" cost table in `references/budget-ladder.md`.

> **Budget-aware seed.** Before designing, check `melange-state.json:budget`. If `total < 6` (too small to seed *and* run a round), shrink the seed to a **single combined probe** (adjacent only) so at least one adaptive round can follow — never let the seed consume more than `floor(total/2)` slots. Record the shrink in the round-0 spice-trail entry.

Launch **two** design subagents in parallel with
`subagent_type: interflux:melange-worker` and the design model from
`references/budget-ladder.md`. Give each the target, GOAL, and the lens-spec
schema expected by `generate-agents.py`:
- **Adjacent:** design `seed.adjacent` domain-specific lenses (default 3) that
  test different mechanisms in the target.
- **Distant:** design `seed.distant` cross-domain lenses (default 2). Reject
  familiar AI analogies and prefer mechanisms from genuinely distant fields.

Use Write to save the specs under
`OUTPUT_ROOT/lens-specs/seed-adjacent.json` and `seed-distant.json` after the
orchestrator creates that directory with `mkdir -p`. The worker cannot run a
shell command. After both writes finish, the **orchestrator** runs the generator
with routing that matches each tier's creative intent:
```bash
# Seed adjacent: reuse a matching canonical lens when available.
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py" "{PROJECT_ROOT}" --from-specs "{OUTPUT_ROOT}/lens-specs/seed-adjacent.json" --mode=skip-existing --registry=auto --json

# Seed distant: preserve novelty instead of letting registry reuse win.
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py" "{PROJECT_ROOT}" --from-specs "{OUTPUT_ROOT}/lens-specs/seed-distant.json" --mode=skip-existing --registry=off --json
```

Inject `GOAL` verbatim into each agent's `task_context` so the seed already pulls toward the goal.

## Run the seed probe

Run **one** direct review per tier in parallel with
`subagent_type: interflux:melange-worker` and `run_in_background: true`. The
orchestrator creates each isolated output dir with `mkdir -p`:
```
OUTPUT_ROOT/round-0/adjacent/
OUTPUT_ROOT/round-0/distant/
```
Each worker reads the generated lens records for its tier and the target, then
uses Write to create `{OUTPUT_ROOT}/round-0/{tier}/fd-seed-{tier}.md` with the
standard Findings Index, Verdict, Summary, Issues Found, and Improvements
sections shown in `phases/probe.md`. Add `Lens: fd-{name}` to each issue so the
Assayer can attribute it. Use local issue IDs; the Assayer assigns global
ledger IDs. Reviewers append `[t]` to aesthetic index lines (so the Assayer
can find taste candidates cheaply). Do not invoke another review skill or
external runtime from this worker.

## Build the lens records

After the seed probe, run a one-shot pass with
`subagent_type: interflux:melange-worker` and the design model over **each**
agent's system prompt + its actual findings to emit a lens record per
`references/fusion.md` (`{id, kind:base, parents:[], domain, axioms[3-7],
primitives[], failure_mode[], findings[]}`). Use Write to create
`OUTPUT_ROOT/lenses/{agent}.json`. These are what `FUSE` candidate selection reads.

> If `interlens` MCP tools are available to the main orchestrator, it may call
> `search_lenses` / `get_lens` and pass the returned context to the worker to
> enrich `domain`/`axioms` — accelerant, not dependency. The worker itself has
> no MCP tools.

## Hand to the assay

Round 0's raw findings now sit in `round-0/*/`. Proceed to `phases/assay.md` to score them into the ledger and compute the first heat map. The loop proper (`retarget → probe → verify → score`) begins at round 1.

## Notes

- Seed is intentionally small: the budget is for the *adaptive* rounds, where it pays off. A fat seed is just flux-review with extra steps.
- If a seed tier fails to produce findings, proceed with the survivor — the loop will widen on its own via STEER-WIDE if novel ground remains.
