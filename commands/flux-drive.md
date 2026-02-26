---
name: flux-drive
description: "Intelligent document review — triages relevant agents, launches only what matters in background mode. Also supports research mode (--mode=research)."
user-invocable: true
argument-hint: "[path to file or directory] [--mode=review|research]"
---

Use the `interflux:flux-drive` skill to review the document or directory specified by the user. Pass the file or directory path as context. Default mode is `review`. Pass `--mode=research` for multi-agent research (or use `/interflux:flux-research` which auto-sets research mode).
