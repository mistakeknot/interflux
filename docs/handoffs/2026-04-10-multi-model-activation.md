---
date: 2026-04-10
session: 37f53668
topic: multi-model activation sprint
beads: [sylveste-fyo3, sylveste-s3z6]
---

## Session Handoff — 2026-04-10 Multi-Model Activation Sprint

### Directive
> Your job is to continue sprint sylveste-fyo3 at Step 2 (Strategy/PRD). Start by running `/clavain:sprint --from-step strategy sylveste-fyo3`. The brainstorm is at `docs/brainstorms/2026-04-09-multi-model-activation-brainstorm.md`.

- Bead: `sylveste-fyo3` — claimed, phase=brainstorm, complexity=4, Tier 3 (interactive)
- Epic has 11 children with dependency graph. Critical path: fyo3.4 (OpenRouter MCP) → fyo3.1 (real qualify) → fyo3.2 (discovery) → fyo3.3 (enforce dispatch)
- Prior session shipped `sylveste-s3z6` (FluxBench closed-loop scoring) — 24 bats tests, 6 scripts, all passing. That's the foundation this epic builds on.
- Stale FluxBench feature beads closed: sylveste-5bwp, sylveste-qroh, sylveste-92bq, sylveste-5gr4, sylveste-ye7y, sylveste-usvf, sylveste-tfj7

### Dead Ends
- Tried asking model selection questions before establishing transport mechanism — user redirected to interview-first flow via AskUserQuestion
- `discover-models.sh` referenced in budget.yaml but doesn't exist in interflux scripts/ — needs creation during execution

### Context
- **Architecture decision: MCP proxy for non-Claude dispatch.** Agent tool only accepts `model:` (Claude tiers). Non-Claude requires an `openrouter-dispatch` MCP server with `review_with_model` tool. This is the root dependency — nothing else works without it.
- **Goals locked in:** cost + diversity co-primary, resilience tertiary. Success = ship first non-Claude review → measure 20%+ cost reduction → observe cross-family convergence on 5+ reviews.
- **Eligible tiers:** all except fd-safety/fd-correctness (Sonnet+ floor). Guarded by 4 mitigations: convergence guard (Claude anchor per stage), rolling FluxBench qualification, shadow-then-enforce per tier (20 shadow runs, 85% convergence), Stage 2 before Stage 1 (50+ successful Stage 2 runs).
- **Sequencing: thin vertical slice.** Build MCP → qualify one model → discover → enforce one tier → ship. Don't build all infrastructure first.
- **Model selection: interrank-driven.** Don't pre-commit to DeepSeek or Gemini — let interrank recommend_model pick Pareto-efficient candidates.
- **FluxBench P0 fix from s3z6:** Never interpolate JSON into Python triple-quoted strings in bash scripts. Use `export _FB_VAR="$data"` + `os.environ['_FB_VAR']`. See `memory/feedback_envvar_python_data.md`.
- **Registry format:** Changed `models: []` to `models: {}` in model-registry.yaml. All scripts expect dict format.
- interflux has its own git repo at `interverse/interflux/` — commit there, not monorepo root.
- interrank change (fluxbench affinity) committed and pushed separately at `interverse/interrank/`.
