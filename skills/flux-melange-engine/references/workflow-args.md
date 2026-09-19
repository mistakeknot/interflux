# Reference: Workflow Fast-Path — Args Contract & Divergences

When flux-melange runs inside Claude Code (main loop, non-interactive), the orchestrator MAY dispatch `workflow/melange-workflow.js` via the Workflow tool instead of driving the prose loop itself. The phase `.md` files remain the spec for both paths; the script is the deterministic runtime for the loop (`SKILL.md` § Runtime dispatch decides which path runs).

## Why a fast-path exists

- The retarget controller is specified as *"a pure function over the ledger"* — in the script it is literal code (heat map, directive selection, continue predicate), immune to prose-runtime drift.
- Orchestration leaves the main context: probe results, assay passes, and phase mechanics no longer consume the orchestrator's window, and a mid-loop compaction cannot destroy loop state.
- Slot budget becomes mechanical (script counters + the Workflow journal), not honor-system arithmetic.
- Journaled resume: `Workflow({scriptPath, resumeFromRunId})` replays completed `agent()` calls from cache — a crashed round N does not re-spend rounds 0..N−1. This replaces the prose path's `melange-state.json` resume detection.

## Dispatch

```
Workflow({
  scriptPath: "{skill base dir}/workflow/melange-workflow.js",
  args: { ...charter contract below }
})
```

Invocation via `/flux-melange` satisfies the Workflow tool's explicit-opt-in requirement (the skill's instructions direct the call).

## Args contract (all required)

Charter (Phase 0) resolves these exactly as for the prose path, then passes them verbatim. Pass real JSON values, not strings. (Defensive: the script also accepts the whole contract as a JSON-encoded string and parses it — some hosts deliver Workflow `args` stringified regardless of how they were passed.)

```json
{
  "inputPath":  "docs/plans/example.md",
  "projectRoot": "/abs/path/to/project",
  "outputRoot": "/abs/.../docs/research/flux-melange/{SLUG}",
  "pluginRoot": "/abs/path/to/interflux plugin (for scripts/generate-agents.py)",
  "slug": "kebab-slug",
  "date": "YYYY-MM-DD",
  "goal": "resolved --goal text",
  "weights": "balanced | risk-hunt | taste | novelty",
  "targetDesc": "1-line target description",
  "quality": "economy | balanced | max",
  "budget": { "totalSlots": 15, "maxRoundSlots": 8, "roundCostFloor": 3 },
  "loop": { "maxRounds": 4, "minRounds": 2, "diminishingThreshold": 1, "wideThreshold": 0.6 },
  "seed": { "adjacent": 3, "distant": 2 },
  "fusion": { "perRoundCap": 2, "sharedHeatGate": 2 },
  "verify": { "mode": "auto | off | all", "noveltyGate": 2, "riskGate": 9 },

  "peers": [ { "kind": "codex", "model": "gpt-6-astra", "timeout_ms": 600000, "invoke": "codex exec --full-auto --skip-git-repo-check --ephemeral -C \"/abs/project\" -m \"gpt-6-astra\" -o \"{outfile}\" - < \"{promptfile}\"" } ],
  "exchange": { "maxRounds": 3 }
}
```

`peers` and `exchange` are OPTIONAL (all other keys are required): omit both for a classic
single-runtime run. When present, `peers[].invoke` must be fully resolved except the
`{promptfile}` placeholder (required) and optional `{outfile}` (both substituted by the
shim — `{outfile}` switches result extraction from stdout-scrape to reading the CLI's
final-message file), and charter must pre-create
`OUTPUT_ROOT/mirrors/{kind}/lenses/` + each mirror's empty `heat-ledger.jsonl`. See
`references/peer-runtimes.md` for detection, isolation, and failure semantics, and
`phases/parley.md` for the exchange the script runs after the mirror syntheses.

`peers[].timeout_ms` is OPTIONAL (default 600000, clamped to 60s–60min): the wall-clock
window the shim gives ONE invocation of that runtime. Size it to the runtime, not to the
task — a runtime measured several times slower than the others starves under a shared
window, and the starvation is silent unless `shim_status` reaches the loop (Sylveste-cg1).

`date` and `slug` MUST come from the charter — Workflow scripts cannot call `Date.now()` / `new Date()`.

Charter still creates `OUTPUT_ROOT/`, `OUTPUT_ROOT/lenses/`, and the empty `heat-ledger.jsonl` before dispatch (agents append to it from round 0).

## What the script returns

A report object: `{slug, rounds_run, halt_reason, slots_spent, findings_total, upheld, refuted, fusions, gain_history, top_finding, synthesis_path, surfaced_count, caveats, ledger_path}`. The orchestrator renders `SKILL.md` § Report (Phase 8) from it. `synthesis_path` and `surfaced_count` are `null` when those artifacts were not produced, and `caveats` says why — treat a null as a missing artifact to regenerate, never as an empty result.

## Documented divergences from the prose path

1. **In-loop phase order is probe → assay → verify → score.** The prose flow lists assay before retarget, but verify's gate (`novelty ≥ 2 OR risk ≥ 9`) and score's yield (`status == upheld`) both need assay scores for the round's *own* findings. The script assays each round's probe output before verifying it (this is the reading `assay.md` § Output already hints at — "score.md (which also re-assays)"). Round 0 gets the same treatment: seed → assay → verify → score.
2. **`melange-state.json` and `round-N-directives.json` are not written per-round.** The Workflow journal + script state replace them. `run-manifest.json` (rounds, halt reason, gain history, spice trail with full directive history, slots spent) carries the audit trail instead — **serialized by the script from controller state** and handed to a haiku scribe that only puts the bytes on disk. The heat ledger, lens records, per-probe finding files, synthesis, and `surfaced.jsonl` are written exactly as in the prose path.
3. **Ledger rows keep empty `convergence_refs`/`disagreement_refs`.** Cross-ledger links live in script state and are handed to the synthesis agent inline (which re-scores anyway). Statuses ARE stamped on disk by the verifiers.
3a. **The synthesis phase is three agents, not one.** `run-manifest.json` (scribe, script-derived) → `{date}-synthesis.md` (the synthesis agent, its **only** artifact, returning just `top_finding` + `caveats`) → `surfaced.jsonl` (a surfacing agent that tabulates the finished report). The prose path may still do all three in one pass; the workflow path may not. A single agent asked for the long-form report *and* the two machine-readable artifacts *and* a structured return spends its whole output window on the report and stalls before the trailing instructions — the 2026-09-13 `orthophoto-pass-and-address-gauge` run wrote a 34 KB synthesis, emitted nothing for the following 6.5 minutes, produced neither companion artifact nor a structured return, and had to be killed by hand. A stalled agent never throws, so `dispatch()`'s degrade-to-null cannot catch it; the only defence is not giving one agent that much to do. Ordering matters too: the script-derived manifest lands *before* the report, so the audit trail survives a synthesis that dies. Each stage degrades independently and names what is missing in `caveats`; `surfaced_count` is `null` (never `0`) when `surfaced.jsonl` was not produced. The surfacing stage runs **even when the synthesis agent returned nothing** and reports `report_found` — writing the report and returning from it are separate failures, and a report that reached disk before its agent died is still a complete, scoreable run.
4. **Verification is batched** — gated findings are verified in chunks of 5 per verifier agent (each chunk = 1 slot) instead of one agent per finding. Budget-clamped verification is logged, never silent.
5. **`--interactive` never uses the workflow path** — scripts cannot `AskUserQuestion` (no per-round confirmation, no GOAL-MET soft stop). Interactive runs stay on the prose loop.
6. **Slot accounting**: design agents (seed design, fused-lens design, STEER-WIDE design) cost tokens but not slots, matching `seed.md`'s clarification; probes, adjudicators, and verifier chunks decrement the counter. The assayer, the synthesis agent, and its two companions (manifest scribe, surfacing agent) are overhead, not slots (per `budget-ladder.md`'s decrement list).
7. **Host portability**: the Workflow tool exists only in the Claude Code main loop. Under Codex, inside subagents, or anywhere the tool is absent, the prose path runs unchanged.
