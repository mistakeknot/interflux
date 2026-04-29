---
name: flux-drive
description: "Intelligent document review — triages relevant agents, runs in background. Supports research mode (--mode=research)."
user-invocable: true
codex-aliases: [flux-drive]
argument-hint: "[path to file or directory] [--mode=review|research] [--phase=<phase>]"
---

Use the `interflux:flux-engine` skill to review the document or directory specified by the user. Pass the file or directory path as context. Default mode is `review`. Pass `--mode=research` for multi-agent research (or use `/interflux:flux-research` which auto-sets research mode).

Note: the underlying skill is named `flux-engine` (not `flux-drive`) to avoid a name collision with this command — both would otherwise resolve to `interflux:flux-drive` and the command would shadow the skill at invocation time.
