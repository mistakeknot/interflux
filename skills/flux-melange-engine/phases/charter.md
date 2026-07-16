# Phase 0 — Charter

Parse the invocation, resolve config, derive identifiers, and lay down the empty ledger + state so the loop has somewhere to write.

## Parse arguments

Parse `$ARGUMENTS`:

| Flag | Default | Meaning |
|------|---------|---------|
| `<path, dir, or inline text>` | required | the review target |
| `--goal="..."` | `"maximize verified novelty×risk surface until dry"` | the north star, injected verbatim into every agent prompt AND used as the retarget relevance filter |
| `--weights=balanced\|risk-hunt\|taste\|novelty` | `balanced` | which derived term the YIELD function boosts |
| `--max-rounds=N` | `4` (cap 6) | CEILING halt |
| `--budget=N\|auto` | `auto` | total agent slots; `auto` derives from `estimate-costs.sh` (see `references/budget-ladder.md`); hard cap 30 |
| `--quality=economy\|balanced\|max` | `balanced` | model routing (see `references/budget-ladder.md`) |
| `--fusion=auto\|N\|off` | `auto` | fusions/round (auto = ≤ 2; depth-2 only on `--quality=max`) |
| `--verify=auto\|off\|all` | `auto` | `auto` = gated on `novelty ≥ 2 OR risk.product ≥ 9` |
| `--peers=off\|auto\|<rt>[:<model>],...` | `off` | multi-runtime mirrors + Parley (see § Resolve peer runtimes; `references/peer-runtimes.md`) |
| `--exchange-rounds=N` | `3` | Parley exchange cap (fixed point usually lands earlier) |
| `--interactive` | off | restores per-round confirmation + the GOAL-MET soft-stop prompt |

If the argument is empty, use `AskUserQuestion` to get a target. If it is not a valid path on disk, treat it as inline text (`INPUT_TYPE = text`).

## Merge config

Resolve in priority order (highest wins):
1. Command-line flags
2. `{PROJECT_ROOT}/.claude/flux-melange.yaml`
3. `${CLAUDE_PLUGIN_ROOT}/config/flux-melange/defaults.yaml`

Read plugin defaults first, then merge the project override (project values win per-key).

## Derive identifiers

```
INPUT_PATH    = <provided path>  (or INPUT_TYPE=text)
PROJECT_ROOT  = nearest ancestor with .git, else directory of INPUT_PATH, else CWD
TARGET_DESC   = 1-line description from reading the target (first 200 lines if file; README/CLAUDE.md if dir)
SLUG          = kebab-case from TARGET_DESC, max 40 chars
DATE          = YYYY-MM-DD
GOAL          = resolved --goal text
WEIGHTS       = resolved --weights
OUTPUT_ROOT   = {PROJECT_ROOT}/docs/research/flux-melange/{SLUG}
```

## Resolve peer runtimes (only when `--peers` ≠ off)

1. Run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/detect-runtimes.sh` (emits one JSON object; exit 0 always).
2. `auto` → every detected runtime; explicit list → keep detected entries, log-and-skip the rest
   (never an error). Claude is always the primary, never a peer.
3. Per surviving runtime, resolve the model (flag `rt:model` > project yaml > plugin defaults)
   and bake the invoke template: substitute `{model}`/`{model_flag}` and `{projectRoot}`, leaving
   only `{promptfile}` for the shim. Result: `PEERS = [{kind, model, invoke}]`.
4. Create per-mirror artifact dirs: `OUTPUT_ROOT/mirrors/{kind}/lenses/` and an empty
   `OUTPUT_ROOT/mirrors/{kind}/heat-ledger.jsonl` for each peer.
5. Add to the plan display: `Peers: {kind (model), ...} — cost ~×(N+1) slots + external billing`,
   and pass `peers` + `exchange` through to the workflow args (references/workflow-args.md).

Peer mirrors REQUIRE the workflow fast-path: in `--interactive` (prose path) warn and run the
primary loop only.

## Initialize ledger + state

Create `OUTPUT_ROOT/` and `OUTPUT_ROOT/lenses/`. Write an empty `heat-ledger.jsonl` (zero bytes) and an initial `melange-state.json`:

```json
{
  "objective": "{GOAL}",
  "weights": "{WEIGHTS}",
  "round": 0,
  "min_rounds": 2,
  "max_rounds": {max_rounds},
  "budget": { "total": {total_slots}, "remaining": {total_slots}, "round_cost_floor": 3 },
  "coverage": { "regions": [], "tiers_used": [], "lens_pairs_fused": [] },
  "heat_map": { "regions": [], "lens_pairs": [], "disagreement_flags": [] },
  "gain_history": [],
  "frontier": [],
  "should_stop": false,
  "halt_reason": null
}
```

Compute `total_slots` per `references/budget-ladder.md` § Initial budget.

## Display plan

```
Flux-melange spice loop on: {INPUT_PATH}
Target: {TARGET_DESC}
Goal:   {GOAL}
Weights: {WEIGHTS}   Quality: {QUALITY}   Fusion: {fusion mode}
Budget: {total_slots} agent slots ({budget source})   Max rounds: {max_rounds}{ [sprint-constrained] if FLUX_BUDGET_REMAINING binds }

Loop: seed → (assay → retarget → probe → verify → score)* → synthesize
Halts: DRY (yield→0) | BUDGET (slots exhausted) | CEILING ({max_rounds}){ | GOAL-MET prompt if --interactive }

Ledger:    {OUTPUT_ROOT}/heat-ledger.jsonl
Synthesis: {OUTPUT_ROOT}/{DATE}-synthesis.md
```

**Auto-proceed (default)** to Phase 1 — charter is deterministic. In `--interactive`, use `AskUserQuestion` ("Proceed (Recommended)", "Adjust budget/rounds", "Cancel").

## Resume detection

If `heat-ledger.jsonl` already exists and is non-empty for this `SLUG`, this is a **resume**: read the last `melange-state.json:round` and re-enter the loop at that round's retarget instead of re-seeding. The append-or-stamp invariant guarantees the existing ledger is replayable.
