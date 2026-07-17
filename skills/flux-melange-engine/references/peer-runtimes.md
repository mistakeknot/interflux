# Reference: Peer Runtimes — Multi-Runtime Mirrors & the Transport Shim

`--peers` runs the SAME melange loop as epistemically independent mirrors on external agent
runtimes (Codex CLI, Hermes Agent), each with its own ledger, lenses, and synthesis, then
reconciles the syntheses in the Parley phase (phases/parley.md). This reference owns the
detection contract, the shim contract, isolation rules, and cost math.

## Flag

```
--peers=off | auto | <runtime>[:<model>][,<runtime>[:<model>]...]
```

- `off` (default) — classic single-runtime melange.
- `auto` — run `scripts/detect-runtimes.sh` and mirror on every available runtime, using
  per-runtime default models from config.
- Explicit list — e.g. `--peers=codex:gpt-5.6-sol,hermes`. A runtime that fails detection is
  logged and skipped (the run proceeds; never an error).
- `--exchange-rounds=N` (default 3) caps the Parley exchange.

## Detection

`scripts/detect-runtimes.sh` probes PATH + `--version` for `codex` and `hermes` and emits one
JSON object. It does NOT probe auth (headless auth checks can hang); an unauthenticated CLI
surfaces at probe time as a SHIM-FAILURE and the mirror degrades per its normal failure path.
The orchestrator (charter) runs detection — the workflow script never does its own.

## Invocation templates (config: `peers.runtimes.*.invoke`)

Resolved by charter (model and cwd baked in), passed to the workflow in `args.peers[].invoke`.
Placeholders the shim substitutes: `{promptfile}` (required — validation throws without it)
and `{outfile}` (optional — when present, the shim substitutes `<promptfile>.out` and reads
the CLI's final message from that file instead of scraping stdout):

| Runtime | Template (default) |
|---------|--------------------|
| codex | `codex exec --full-auto --skip-git-repo-check --ephemeral -C "{projectRoot}" -m "{model}" -o "{outfile}" - < "{promptfile}"` |
| hermes | `cd {projectRoot} && hermes -z "$(cat {promptfile})" [-m {model}] --yolo` |

Notes: `codex exec` (never bare `codex` — that opens interactive mode); `--full-auto` =
workspace-write sandbox + auto-approval; `--skip-git-repo-check` because melange targets are
not always inside a git repo; `--ephemeral` keeps dozens of probe sessions out of codex's
session store; `-o` writes ONLY the final agent message to `{outfile}` — verified 2026-07-16
(26-byte clean JSON vs 4.7KB event noise on stdout). `--output-schema` was evaluated and
REJECTED: it demands OpenAI strict mode (`additionalProperties: false` + all-required at
every object level, HTTP 400 otherwise), incompatible with melange's loose schemas — the
"end your reply with a single JSON object" contract + shim-side extraction stays. Hermes `-z`
is the headless one-shot; `--yolo` auto-accepts tool use so mirror probes can write findings
files; hermes has no `-o`/`{outfile}` equivalent, so its shim path scrapes stdout. Both
templates are config, not code — fix CLI drift in `flux-melange.yaml` without touching the
engine.

## The transport shim

Workflow scripts can only spawn Claude agents, so each mirror call is relayed by a **shim**: a
haiku agent whose entire charter is *run the task on the external CLI and relay the structured
output verbatim*. Rules the shim enforces:

1. Stages the task prompt in a private `mktemp -d` dir under `{outputRoot}/mirrors/{kind}/tmp/`
   (`shim-XXXXXX/task.md` — mktemp, not filename choice, is what makes concurrent shims
   collision-proof) and appends the JSON Schema the external model must satisfy (the same
   schema the native path validates against).
2. One Bash call, 600s timeout, using the invocation template.
3. Extracts the FINAL JSON object — from the `{outfile}` final-message file when the template
   carries that placeholder, otherwise from stdout; on parse failure re-asks the external CLI
   once.
4. Relays verbatim — the shim never adds, drops, merges, rescores, or rewords. Shim model is
   haiku *by construction*: transport must stay too dumb to contaminate the mirror's
   independence.
5. On CLI absence / double failure / timeout: returns a minimally valid object with
   `SHIM-FAILURE: <reason>` in a required string field, so the loop's existing
   survivor-degradation handles it.

Schema validation still happens at the shim's own tool-call layer, so malformed external output
retries hit the shim (which re-asks the CLI), not the controller.

## Isolation (what keeps mirrors epistemically independent)

- Own artifact tree: `{OUTPUT_ROOT}/mirrors/{kind}/` (ledger, lenses, round dirs, synthesis,
  surfaced.jsonl, run-manifest.json). The primary keeps the classic root paths, so resume
  tooling and fetch-findings are unaffected.
- Own lens namespace: generated fd-* agent names carry a per-runtime suffix (`-cox` for codex,
  `-hex` for hermes — first two letters + `x`), and spec files carry a `-{kind}` tag, so the
  shared `.claude/agents/` directory never collides and `--mode=skip-existing` never
  cross-contaminates.
- No shared state: mirrors never read the primary's ledger, findings, or lens records (and vice
  versa) until Parley — where the collision is the point, and it happens over *syntheses*, with
  attribution, not over raw pools.
- The seed's distant-tier constraints, fusion charter, and verify gates apply identically in
  mirrors — same shape, different mind.

## Cost & budget

Each mirror gets its own slot pool equal to the primary's (`budget.totalSlots`) and decrements
it by measured dispatch exactly like the primary — so `--peers` with N mirrors costs roughly
(N+1)× the single-runtime run in slots, plus the external providers' own billing (not metered
here; shims are haiku-cheap). Parley adds ≤ `(runtimes + 1) × exchange.max_rounds` agent calls
outside the slot pools. Charter multiplies the plan display accordingly; the 30-slot hard cap
applies per loop, not to the sum.

## Trust boundary

Peer mirrors run external agents with **auto-approved tool use** — that is what makes headless
mirrors possible, and it is a real permission decision, not an implementation detail:

- `codex exec --full-auto` = workspace-write **sandbox scoped to projectRoot** + auto-approval.
- `hermes --yolo` = auto-approval with **no sandbox**. Prefer codex-only `--peers` on repos you
  do not fully trust; enable the hermes mirror only where an unsandboxed agent is acceptable.
- Only enable `--peers` at all on targets/repos you trust: mirror probes read the target and
  repo files and write findings artifacts, and prompt content includes prior agents' output.

Injection hardening: `kind` and `model` are the only externally-influenced strings interpolated
into shell command lines, and both are regex-validated twice — at charter
(`^[a-z][a-z0-9-]{1,15}$` / `^[A-Za-z0-9._:-]{1,64}$`) and again at the workflow script's parse
chokepoint (which throws). Templates keep `{projectRoot}`/`{promptfile}` double-quoted; the shim
constrains prompt filenames to `[a-z0-9-]`. Invoke templates themselves are **trusted config**
(plugin defaults or the project's own `flux-melange.yaml`) — a hostile project config is already
outside this threat model, same as hooks.

## Failure semantics

| Failure | Effect |
|---------|--------|
| Runtime not detected | skipped at charter; logged in plan |
| Mirror loop dies (seed produces no lenses, both seed probes fail) | mirror reported `failed`, caveat added; primary unaffected |
| Primary loop dies | whole workflow errors (unchanged from classic behavior) |
| Shim double-failure on one call | that call degrades exactly like a native probe failure (survivors proceed) |
| < 2 syntheses at Parley | phase skipped with caveat |

## Relationship to interpeer

interpeer's council/mine modes are interactive, command-level cross-AI review. Parley is the
same epistemology embedded in the melange workflow: independent full loops instead of one-shot
second opinions, and a fixed-point exchange instead of single-round disagreement extraction.
If you want a quick cross-model take on a diff, use interpeer; if you want two (or three)
complete adaptive reviews that then argue to equilibrium, use `--peers`.
