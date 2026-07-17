---
name: flux-drive
description: "Intelligent document review — triages relevant agents, runs in background. Supports research mode (--mode=research)."
user-invocable: true
codex-aliases: [flux-drive]
argument-hint: "[path to file or directory] [--mode=review|research] [--phase=<phase>]"
---

Use the `interflux:flux-engine` skill to review the document or directory specified by the user. Pass the file or directory path as context. Default mode is `review`. Pass `--mode=research` for multi-agent research (or use `/interflux:flux-research` which auto-sets research mode).

Routing note: if the target is a discovery-shaped question (gap analysis, "what are we missing", design-space or plan exploration) rather than a bounded artifact check, suggest escalating to `/interflux:flux-melange <target> --goal="..."` — the adaptive loop is the default for open-ended analysis/planning work. See `docs/guide-choosing-flux-command.md`.

Note: the underlying skill is named `flux-engine` (not `flux-drive`) to avoid a name collision with this command — both would otherwise resolve to `interflux:flux-drive` and the command would shadow the skill at invocation time.
