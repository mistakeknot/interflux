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

## Importing an independently packaged review

A run can take in one separately produced review (a receipt plus a report) as external, unverified evidence. This is a file import, not a live peer, and it does not change `--peers=off` or ordinary runs. The operator imports it into an existing run before synthesis begins:

```bash
python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/import-melange-review.py" \
  --run-dir <run> --receipt <receipt.json> --report <report.md> \
  --report-sha256 <64 lowercase hex>
```

`--report-sha256` is the hash the operator recorded when the report was packaged; a mismatch is refused. The coordinator then records why the review applies to the target and assimilates the bundle after the loop (`skills/flux-melange-engine/references/import-review.md`).

Advisory format contract for whoever configures the reviewer dispatch: Write each finding as `### P1: Title` or `- P1: Title`, using P0–P3, without emphasis, embedded IDs or severity tables. Cite a real `path:line` or `path:start-end` when known; do not invent one. Use continuation prose for evidence. Omit zero-count breakdown bullets. If supplying FINDINGS, make its counts exact. End after a blank line with exactly VERDICT: PASS, VERDICT: PASS WITH NOTES, or VERDICT: FAIL. Include no fences or HTML comments.

`flux-melange` is the apex of the interflux escalation ladder — `flux-drive` (single triaged pool) → `flux-review` (fixed N tracks at static semantic distances, blind fan-out, convergence synthesis) → `flux-explore` (autonomous rounds, but monotonically *further out*) → **`flux-melange`** (a *closed loop*: each round's targeting is a function of what the previous round found, lenses *combine* instead of only aggregating, and findings rank on Novelty/Risk/Taste, not severity alone). See `docs/guide-choosing-flux-command.md` for when to reach for which.

Note: the underlying skill is named `flux-melange-engine` (not `flux-melange`) to avoid command-shadowing — the command and skill would otherwise both resolve to `interflux:flux-melange` and the command would shadow the skill at invocation time. Same pattern as `/flux-drive` → `interflux:flux-engine` and `/flux-review` → `interflux:flux-review-engine`.
