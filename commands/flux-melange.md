---
name: flux-melange
description: "Goal-seeking spice loop — adaptive review rounds steer toward the heat (novelty/risk/disagreement) found so far, fuse high-tension lens pairs into hybrid intersection-detectors, score every finding on Novelty/Risk/Taste, and surface the spice."
user-invocable: true
codex-aliases: [flux-melange]
argument-hint: "<path, dir, or inline text> [--goal=\"...\"] [--weights=balanced|risk-hunt|taste|novelty] [--max-rounds=N] [--budget=N] [--quality=economy|balanced|max] [--fusion=auto|N|off] [--verify=auto|off|all] [--peers=off] [--interactive]"
disable-model-invocation: true
---

Use the `interflux:flux-melange-engine` skill to run a goal-seeking, multi-round deep review of the target. Pass `$ARGUMENTS` through verbatim. The skill owns charter parsing, the seed round, the heat-ledger control loop (assay → retarget → probe → verify → score → loop gate), runtime lens fusion, and the surfacing-first synthesis.

Peer mirrors (`--peers=auto` or an explicit runtime list) are temporarily disabled.
Their external CLIs can write findings without the before-disk redaction guard, so
melange stops before dispatch when peer mode is requested. The default is
`--peers=off`.

`flux-melange` is the apex of the interflux escalation ladder — `flux-drive` (single triaged pool) → `flux-review` (fixed N tracks at static semantic distances, blind fan-out, convergence synthesis) → `flux-explore` (autonomous rounds, but monotonically *further out*) → **`flux-melange`** (a *closed loop*: each round's targeting is a function of what the previous round found, lenses *combine* instead of only aggregating, and findings rank on Novelty/Risk/Taste, not severity alone). See `docs/guide-choosing-flux-command.md` for when to reach for which.

Note: the underlying skill is named `flux-melange-engine` (not `flux-melange`) to avoid command-shadowing — the command and skill would otherwise both resolve to `interflux:flux-melange` and the command would shadow the skill at invocation time. Same pattern as `/flux-drive` → `interflux:flux-engine` and `/flux-review` → `interflux:flux-review-engine`.
