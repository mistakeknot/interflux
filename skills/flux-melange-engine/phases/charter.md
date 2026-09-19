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
| `--producer=<kind>/<model>` | unset | enable consequential validation routing relative to the producing model; required identity is persisted in the plan and report |
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

### Select the route before detecting it

**Bulk mirrors and consequential validation resolve from different tables, and
only one of them is a routing decision.** A mirror is an independent second
opinion with no producer to be separated from, so its model is simply whatever
`peers.runtimes` resolves to in step 3 below (flag > project yaml > plugin
defaults), with `detect-runtimes.sh` supplying what this environment can
actually reach. Never name a mirror model in prose — it goes stale the moment
the config is re-ruled, and the plan display prints only the resolved value, so
the substitution would be invisible in the run output.

When `--producer` is present, resolve a consequential validation chain instead
— that IS a routing decision, because the reviewer must differ from the
producer:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/select-review-route.py" \
  --purpose validation --producer "$PRODUCER"
```

The selector returns complete profiles in preference order. A Claude/Fable or
Kimi producer selects Astra/high/Standard first; an Astra producer selects
Claude/Fable, then Kimi, then GPT-5.6 Sol, and never Astra. Keep the sealed
first-pass output unavailable to the reviewer until its initial findings are
complete. Intersect the returned chain with detected runtimes and choose the
first available candidate. A Codex candidate whose installed version is below
`minimum_codex_version` is unavailable. After dispatch, advance to the next
candidate only for explicit model unavailability, account-access absence, or
insufficient Codex version. Policy/misalignment 403s and other configuration
4xx errors are terminal; retry 429s on the same model with a bounded retry.

Without `--producer` there is no chain to resolve: go straight to detection.
The mirror's economics still must not drift with the caller's global Codex
default, but that is handled by the invoke template pinning `service_tier` and
`model_reasoning_effort` explicitly — not by routing. `--purpose bulk` remains
available and reads `peers.runtimes.codex`, the same table step 3 uses, so the
two paths cannot disagree:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/select-review-route.py" --purpose bulk
```

Record `producer_identity` and the selected reviewer profile in the run plan
and final report. Validation without a producer identity is invalid; do not
guess it from the current host.

1. Run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/detect-runtimes.sh` (emits one JSON object; exit 0 always).
   Each runtime reports `model` + `model_reason` (what this environment can actually reach) and
   `sandboxed`. **Consent gate:** when `peers.consent.auto_includes_unsandboxed` is false, `auto`
   keeps only `sandboxed: true` runtimes — unsandboxed ones are still listed in the plan, marked
   skipped-for-consent, and run only when the user NAMES them in `--peers`. Naming is consent; an
   explicit list is never filtered by this gate. Always surface each mirror's resolved model and
   `sandboxed` state in the plan display, so a downgrade is visible before the run rather than
   discovered in the report.
2. For bulk review, `auto` → every detected external runtime and explicit list → keep detected
   entries, log-and-skip the rest (never an error). For consequential validation, use the
   producer-relative candidate chain above; Claude/Fable may be the reviewer when the host or
   producer is not Claude. A reviewer must never resolve to the producer model.
3. Per surviving runtime, resolve the model (flag `rt:model` > project yaml > plugin defaults)
   and bake the invoke template: substitute `{model}`/`{model_flag}`, `{projectRoot}`, and
   `{pluginRoot}` (= `${CLAUDE_PLUGIN_ROOT}`), leaving only `{promptfile}` (and `{outfile}`, if
   the template carries it) for the shim. `{pluginRoot}` lets a **no-CLI HTTP runtime** (e.g.
   `kimi`) point its invoke at a plugin-shipped wrapper script instead of a PATH binary — the
   wrapper POSTs `{promptfile}` to an API and writes the final message to `{outfile}`, so the
   shim's file-extraction path is identical to codex's `-o`.
   Result: `PEERS = [{kind, model, invoke}]`.
   **Validate before baking** (the values land inside shell commands): runtime kind must match
   `^[a-z][a-z0-9-]{1,15}$`, model must match `^[A-Za-z0-9._:-]{1,64}$` — REJECT the flag
   otherwise (the workflow script re-validates at its chokepoint and will throw). Keep the
   template's double quotes around `{projectRoot}`, `{pluginRoot}`, and `{promptfile}`.
4. Create per-mirror artifact dirs: `OUTPUT_ROOT/mirrors/{kind}/lenses/` and an empty
   `OUTPUT_ROOT/mirrors/{kind}/heat-ledger.jsonl` for each peer.
5. Add to the plan display: `Peers: {kind (model), ...} — cost ~×(N+1) slots + external billing`
   plus the trust warning: `⚠ peer mirrors run external CLIs with auto-approved tool use
   (codex: workspace-write sandbox; hermes and the kimi CLI lane: UNSANDBOXED in the project
   root)`. Name every unsandboxed lane — this warning is the only place a user sees it before
   the run starts, so an omission reads as an assurance. Pass `peers` + `exchange` through to
   the workflow args (references/workflow-args.md).

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
