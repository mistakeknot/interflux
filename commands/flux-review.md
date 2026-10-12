---
name: flux-review
description: "Multi-track deep review — agents across semantic distance (adjacent→orthogonal→distant→esoteric), parallel flux-drive + cross-track convergence."
user-invocable: true
codex-aliases: [flux-review]
argument-hint: "<path, topic, or inline text> [--tracks=auto|2|3|4] [--creative] [--quality=balanced|economy|max] [--interactive]"
disable-model-invocation: true
---

Use the `interflux:flux-review-engine` skill to run a multi-track deep review of the target. Pass `$ARGUMENTS` through verbatim. The skill handles per-track agent design across semantic-distance tiers, parallel flux-drive review dispatch, cross-track synthesis, and the final report.

Routing note: this command is the escalation for bounded research and one-pass semantic-distance review. Suggest `/interflux:flux-melange <target> --goal="..."` only for high-stakes work: architecture pivots, security or data-loss hunts, pre-mortems, and foundational plans. Use its balanced three-round profile; suggest to-dry only when the user explicitly asks. See `docs/guide-choosing-flux-command.md`.

Note: the underlying skill is named `flux-review-engine` (not `flux-review`) to avoid command-shadowing — the command and skill would otherwise both resolve to `interflux:flux-review` and the command would shadow the skill at invocation time. Same pattern as `/flux-drive` → `interflux:flux-engine`.
