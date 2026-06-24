# Phase 1 — First Taste (Round 0)

The **only** round not steered by heat. Its job is to populate the ledger with first findings, the lens records that fusion and retargeting depend on, and the initial heat map — so round 1's controller has something to be a pure function *of*.

## Design the seed lenses (2 tiers, compact)

Seed deliberately mirrors `flux-review`'s two outer tiers — **adjacent** (domain experts) + **distant** (cross-domain isomorphisms) — not the full 4-track lattice. Two tiers give the controller both a "deep" and a "wide" starting signal without spending the budget before the loop begins.

Launch **two** design subagents in parallel (model per `references/budget-ladder.md`):
- **Adjacent:** reuse the Track A prompt from `flux-review-engine/phases/track-dispatch.md` (5 → trim to `seed.adjacent` agents, default 3).
- **Distant:** reuse the Track C prompt (anti-clustering: the 13 blocked AI-analogy domains), `seed.distant` agents (default 2).

Save specs to `.claude/flux-gen-specs/{SLUG}-seed-adjacent.json` and `{SLUG}-seed-distant.json`, then generate via the standard path:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py {PROJECT_ROOT} --from-specs <specs> --mode=skip-existing --json
```

Inject `GOAL` verbatim into each agent's `task_context` so the seed already pulls toward the goal.

## Run the seed probe

Run **one** flux-drive-style review per tier, in parallel, `run_in_background: true`, each with its own isolated output dir (the issue-#6 trick):
```
OUTPUT_ROOT/round-0/adjacent/
OUTPUT_ROOT/round-0/distant/
```
Each writes the standard Findings Index + verdict. Reviewers append `[t]` to any index line they judge aesthetic (so the assayer can find taste candidates cheaply).

## Build the lens records

After the seed probe, run a one-shot pass (the design model) over **each** agent's system prompt + its actual findings to emit a lens record per `references/fusion.md` (`{id, kind:base, parents:[], domain, axioms[3-7], primitives[], failure_mode[], findings[]}`). Write to `OUTPUT_ROOT/lenses/{agent}.json`. These are what `FUSE` candidate selection reads.

> If `interlens` MCP tools are available, also call `search_lenses` / `get_lens` to enrich `domain`/`axioms` from the lens graph — accelerant, not dependency.

## Hand to the assay

Round 0's raw findings now sit in `round-0/*/`. Proceed to `phases/assay.md` to score them into the ledger and compute the first heat map. The loop proper (`retarget → probe → verify → score`) begins at round 1.

## Notes

- Seed is intentionally small: the budget is for the *adaptive* rounds, where it pays off. A fat seed is just flux-review with extra steps.
- If a seed tier fails to produce findings, proceed with the survivor — the loop will widen on its own via STEER-WIDE if novel ground remains.
