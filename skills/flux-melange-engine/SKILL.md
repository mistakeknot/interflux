---
name: flux-melange-engine
description: Invoked from /flux-melange — runs a goal-seeking, multi-round review loop. A single append-only HEAT LEDGER is threaded between rounds; each round's targeting (DEEPEN/FUSE/STEER-WIDE/PROBE-DISAGREEMENT) is computed from the prior round's findings, lenses fuse into hybrid intersection-detectors, findings score on Novelty/Risk/Taste, and synthesis surfaces the spice. Internal engine; users invoke via the slash command.
---

# Flux-Melange — Goal-Seeking Spice-Loop Review Engine

Run a **closed-loop** review. Where `/flux-review` fans out a fixed set of tracks *once*, blind, and synthesizes at the end, `/flux-melange` threads one scored, append-only **heat ledger** between adaptive rounds. Each round's targeting is a pure function of what the previous round found — steering compute *toward the heat* (novelty / risk / disagreement) instead of blindly *further out*. Two lenses can **fuse** into a third hybrid lens that reports only findings invisible to either parent alone. Every finding scores on **Novelty / Risk / Taste**, and the final synthesis **surfaces the spice** — the novelty×risk frontier, the top fusions, the boldest taste calls — not a flat severity list.

> **Spice metaphor (on-brand, load-bearing).** *Melange* (Dune's spice) grants prescience — the eye that sees across distance. The loop **assays** each round's spice, **steers toward the heat**, **fuses reagents** into new lenses, and ends with the **eye of distance** (synthesis). The names are mnemonics for real mechanics, not decoration.

## Why this earns being a new mode (not flux-review + flags)

`flux-review` is **open-loop**: it triages a track count exactly once, runs every track in a single blind parallel batch, and synthesizes at the end. No finding ever flows back into what later agents target, and lenses only ever **aggregate** — their *independence* is the convergence signal. `flux-melange` **closes the loop** and adds three capabilities the static lattice cannot express:

1. **Heat-steering control loop** — round N+1's targeting is computed from round N's findings via a typed directive vocabulary, optimized against an explicit `--goal` with real stop conditions.
2. **Lens fusion** — a runtime-synthesized *third* agent built from two parents' axioms, with an intersection-only charter and an adversarial emergence gate. flux-review's convergence (a correlation detector that rewards *agreement*) becomes one class inside melange's complement: a constructed **interaction detector** that rewards productive *disagreement*. (Convergence still falls out as a class, so melange strictly contains flux-review.)
3. **Novelty / Risk / Taste classification + surfacing** — severity-only ranking is replaced with orthogonal axes, so an elegant-but-P3 finding or a rare-catastrophe (blast 3 × likelihood 1) that every ancestor structurally buries now *leads* the report.

## Runtime contract (no new primitives)

The loop is expressible in the exact primitives `flux-engine` / `flux-review-engine` already use — and inside Claude Code there is additionally a **workflow fast-path** (`workflow/melange-workflow.js`, dispatched per § Runtime dispatch below) that runs the same loop as a background Workflow script with the controller as literal code. The prose path rides these primitives:

| Primitive | Realization |
|-----------|-------------|
| Parallel fan-out | N concurrent `Agent` calls with `run_in_background: true` |
| Pipeline | Sequential phase files, each reading the prior phase's on-disk artifacts |
| Loop-until-X | A controller phase that re-enters `phases/retarget.md` until `melange-state.json:should_stop == true` (a crisp boolean is the only loop condition a prose-driven runtime can reliably honor) |
| Schema-validated agents | JSON specs (incl. fused-lens specs) through `generate-agents.py --from-specs … --json` (the existing validated `fd-*` contract) |
| Budget scaling | `estimate-costs.sh` + `budget.yaml` + a `MELANGE_BUDGET_REMAINING` accumulator decremented per round by measured cost |
| Per-probe output isolation | Every probe gets its own `--output-dir` (the "issue #6" trick) so concurrent probes on the same `INPUT_PATH` never clobber |

The **heat ledger** is the only genuinely new object. See `references/ledger-schema.md`.

## Phase flow

| Phase | File | Role |
|-------|------|------|
| 0 — Charter | `phases/charter.md` | Parse args / `--goal` / `--weights`, merge config, derive `SLUG`/`PROJECT_ROOT`/`TARGET_DESC`, init empty ledger + state, compute initial budget. |
| 1 — First taste (round 0) | `phases/seed.md` | The *only* non-heat-driven round: a compact 2-tier (adjacent + distant) seed populates the ledger with first findings, **lens records**, and a heat map. |
| 2 — Assay | `phases/assay.md` | One **Assayer** subagent (never the reviewers) scores Novelty/Risk/Taste, dedups into clusters, runs the fusion **emergence gate**, appends to ledger. |
| 3 — Retarget | `phases/retarget.md` | The **controller** (a pure function over the ledger) computes the heat map and emits `round-N-directives.json` — 2–4 typed directives with budget weights. |
| 4 — Probe | `phases/probe.md` | Parallel background `Agent`s, per-directive output dirs: run single-lens and fused-lens probes; each writes a standard Findings Index + verdict. |
| 5 — Verify | `phases/verify.md` | **Conditional** cheap-model pass: re-read cited locations for high-novelty / high-risk findings only; stamp `upheld` / `refuted`. |
| 6 — Score + loop gate | `phases/score.md` | Assay the round, link convergence/disagreement refs across the whole ledger, decrement budget, evaluate the continue predicate → write `should_stop`. |
| 7 — Synthesize | `phases/synthesize.md` | One Opus agent (the **eye of distance**) over the full ledger surfaces the five views + spice trail; write dated `synthesis.md`. |
| 7.5 — Parley | `phases/parley.md` | Only with `--peers` (`references/peer-runtimes.md`): phases 1–7 also ran as independent mirrors on external runtimes (codex/hermes); per-runtime advocates now adversarially exchange concessions/challenges until a moderator detects the fixed point (**epistemic equilibrium**); residual contested topics go to the user for tie-break. |
| 8 — Report | inline below | Print ledger + synthesis paths, the per-round hotspot/directive trail, halt reason, total cost, regeneration hints; with peers: the equilibrium verdict + contested-topic tie-break. |

The loop is **Phase 3 → 4 → 5 → 6**, re-entering from 6 to 3 while `should_stop == false`.

## Step 0: Read the charter phase and proceed

**Read `phases/charter.md` now.** It owns argument parsing, config merge (flags > `{PROJECT_ROOT}/.claude/flux-melange.yaml` > `${CLAUDE_PLUGIN_ROOT}/config/flux-melange/defaults.yaml`), derivation of `SLUG`/`PROJECT_ROOT`/`TARGET_DESC`/`DATE`, ledger + state initialization, the initial budget computation, and the plan display.

After charter, display the plan and (unless `--interactive`) auto-proceed — triage is deterministic.

## Runtime dispatch: workflow fast-path vs prose loop

After charter, choose the execution path. Use the **workflow path** when ALL of:

1. The **Workflow tool is available** in this session (Claude Code main loop — it is absent under Codex and inside subagents);
2. **Not `--interactive`** (scripts cannot AskUserQuestion — no per-round confirmation, no GOAL-MET prompt);
3. **Not resuming a prose-mode run** (a non-empty `heat-ledger.jsonl` with no prior workflow run for this SLUG → finish on the prose path).

Otherwise run the **prose path** (Steps 1–3 below). The phase files are the spec for both paths.

**Peer mirrors require the workflow path.** When charter resolved `--peers` (see `phases/charter.md` § Resolve peer runtimes and `references/peer-runtimes.md`) but the prose path is forced (`--interactive`, no Workflow tool), warn and run the primary loop only — the mirror loops and Parley exist only in the script in v1.

**Workflow path:**

1. Charter has already parsed args, merged config, derived identifiers, computed the budget, and created `OUTPUT_ROOT/` + `lenses/` + the empty ledger — all of that still happens here, in the orchestrator.
2. Dispatch (invocation via `/flux-melange` satisfies the Workflow tool's explicit-opt-in requirement):
   ```
   Workflow({
     scriptPath: "{this skill's base dir}/workflow/melange-workflow.js",
     args: { ...charter contract — see references/workflow-args.md }
   })
   ```
3. The workflow runs in the background (watch with /workflows). On completion, take the returned report object and render Phase 8 (§ Report below) from it. Verify the synthesis file exists before reporting success; if the report carries `caveats`, surface them verbatim.
4. **Resume after a crash/kill:** `Workflow({scriptPath, resumeFromRunId: "<prior runId>"})` — completed agent calls replay from the journal cache. This replaces prose-mode resume detection.
5. Divergences from the prose path (in-loop phase order, state-file substitution, batched verification, slot accounting) are documented in `references/workflow-args.md` — read it before dispatching or debugging a workflow run.

## Step 1: First taste (round 0)

**Read `phases/seed.md` now.** Round 0 is the only round NOT steered by heat: it seeds the ledger with a compact two-tier flux-review-style pass (adjacent + distant) plus the lens records that fusion and retargeting depend on.

## Step 2: The loop

Run **assay → retarget → probe → verify → score** in order, re-entering at retarget while the loop gate leaves `should_stop == false`.

**Read each phase file when you reach it:**
- `phases/assay.md` — scoring + clustering + emergence gate
- `phases/retarget.md` — the controller and the directive vocabulary (`references/directive-vocabulary.md`)
- `phases/probe.md` — dispatch templates, fusion-spec generation, output isolation
- `phases/verify.md` — conditional verification gating
- `phases/score.md` — cross-ledger linking + the continue predicate (the loop gate)

Supporting references, read on demand:
- `references/ledger-schema.md` — the ledger + state object shapes
- `references/heat-scoring.md` — the Novelty/Risk/Taste rubrics and heat formula
- `references/fusion.md` — candidate selection, hybrid-lens charter, emergence gate
- `references/directive-vocabulary.md` — DEEPEN / FUSE / STEER-WIDE / PROBE-DISAGREEMENT semantics
- `references/budget-ladder.md` — budget accumulator + per-directive fan-out scaling

## Step 3: Synthesize and report

**Read `phases/synthesize.md` now** to produce the surfacing-first report.

### Report (Phase 8)

Print:
```
Flux-melange complete for: {INPUT_PATH}
Goal: {GOAL}   Weights: {WEIGHTS}
Rounds run: {N} (halt: {DRY | BUDGET | CEILING | GOAL-MET})

Spice trail:
{for each round:}
  Round {r}: yield {yield}, {n} new clusters — directives: {directive summary}

Fusions: {total_fusions} attempted, {emergent} produced emergent findings
Top finding (argmax heat): {one-line}

Ledger:    docs/research/flux-melange/{SLUG}/heat-ledger.jsonl
Synthesis: docs/research/flux-melange/{SLUG}/{DATE}-synthesis.md
Total cost: ~${cost}

To rerun the discovered lenses as a flat review: /flux-drive {INPUT_PATH}
To regenerate a fused lens: /flux-gen --from-specs .claude/flux-gen-specs/{SLUG}-fusion-{k}.json
```

With `--peers`, append (from the report's `peers` + `equilibrium` fields):
```
Peer mirrors:
  {runtime} ({model}): {rounds} rounds (halt {reason}), {upheld}/{total} upheld — synthesis: {path}
  {or: "{runtime}: FAILED — {caveat}"}

Parley: {rounds} exchange round(s) — equilibrium {REACHED | NOT REACHED (capped)}
Consensus: {agreed_count} claims   Contested: {n} topics
Equilibrium:    {OUTPUT_ROOT}/equilibrium.md
Disagreements:  {OUTPUT_ROOT}/disagreements.jsonl
```

**Tie-break (orchestrator only — never inside the workflow):** if `equilibrium.contested` is
non-empty, present the top topics by heat (≤ 4) via `AskUserQuestion` — one question per topic,
each runtime's argument as an option (plus "both partially right" / "defer"), attributed by
runtime. Append the rulings to `equilibrium.md` under `## Rulings` and mention any topics left
unruled. In non-interactive contexts, list the contested table in the report instead of asking.

## Notes

- **Crash-safety.** Every phase only *appends* findings or *rewrites status fields* — it never mutates a claim. A mid-loop crash leaves a replayable ledger; rerunning resumes from the last completed round.
- **Three independent halts** plus an optional soft one: **DRY** (yield → 0), **BUDGET** (accumulator exhausted, hard), **CEILING** (`max_rounds`), and — only in `--interactive` — **GOAL-MET** (AskUserQuestion: keep spending?). `min_rounds = 2` guards against one unlucky round quitting the loop early.
- **The steering signal is decoupled from raw novelty.** Heat = novelty × risk *yield-density*, not novelty alone — otherwise "go toward novelty" + "novelty = unexplored" manufactures a shallow-novel trickle that never lets DRY fire. `STEER-WIDE` is therefore a *reserved* directive, not forced every round.
- **Degraded modes.** If `interlens` MCP tools (`combine_lenses` / `find_contrasting_lenses`) are unavailable, fusion falls back to controller heuristics over lens records — an accelerant, not a dependency. If a probe fails, its directive is dropped and the round proceeds with survivors (same graceful-degradation posture as flux-review tracks). Peer mirrors extend this posture: an undetected runtime is skipped at charter, a dead mirror becomes a caveat (primary unaffected), and Parley is skipped below 2 surviving syntheses (`references/peer-runtimes.md` § Failure semantics).
- **Relationship to convergence.** flux-review's cross-track convergence is preserved but *reframed and demoted*: high convergence = high confidence but LOW novelty (commodity you can trust but shouldn't be excited by). It is one synthesis section, no longer the headline.
