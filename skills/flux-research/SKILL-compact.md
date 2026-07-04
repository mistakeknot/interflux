# Flux Research (compact)

DEPRECATED — use `interflux:flux-drive` with `mode=research` instead. Kept for backward compatibility.

## When to Invoke

This skill auto-routes to flux-drive in research mode. Use `/interflux:flux-drive` directly.

## Original Workflow (archived)

1. **Triage** — Build query profile (type, keywords, scope, depth), score 5 research agents, confirm with user
2. **Launch** — Prepare output dir, build per-agent prompts with domain directives, dispatch in parallel
3. **Synthesize** — Delegate to intersynth synthesis agent (never read agent output yourself)

## Query Types & Agent Affinity

| Type | Primary agents | Secondary |
|------|---------------|-----------|
| onboarding | repo-research-analyst | learnings, framework-docs |
| how-to | best-practices, framework-docs | learnings |
| why-is-it | git-history, repo-research | learnings |
| what-changed | git-history | repo-research |
| best-practice | best-practices | framework-docs, learnings |
| debug-context | learnings, git-history | repo-research, framework-docs |
| exploratory | repo-research, best-practices | all others |

## 5 Research Agents

best-practices-researcher, framework-docs-researcher, git-history-analyzer, learnings-researcher, repo-research-analyst

## Key Rules

- Launch agents with score >= 2 (from affinity table)
- Domain bonus: +1 for agents with Research Directives in detected domains
- Depth controls timeout: quick (30s), standard (2min), deep (5min)
- Synthesis delegated to `intersynth:synthesize-research` — host never reads agent output files
- Output goes to `{PROJECT_ROOT}/docs/research/flux-research/{query-slug}/`

---
*For domain detection, agent prompt templates, and monitoring details, read SKILL.md.*
