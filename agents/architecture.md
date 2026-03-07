# Architecture

```
interflux/
├── agents/review/       # 8 fd-* review agents (7 technical + fd-systems cognitive)
├── agents/research/     # 5 research agents (best-practices, framework-docs, git-history, learnings, repo-research)
├── commands/            # 3 commands: flux-drive, flux-gen, flux-research
├── skills/flux-drive/   # Review orchestration (triage, launch phases, synthesis) + references/
├── skills/flux-research/# Research orchestration
├── config/flux-drive/domains/  # 11 domain detection profiles + index.yaml
├── docs/spec/           # flux-drive protocol spec v1.0.0 (9 documents)
├── hooks/               # SessionStart (interbase-aware)
├── scripts/             # content-hash, generate-agents, validate-roster
└── tests/structural/    # 120 pytest tests
```

## flux-drive (Review Orchestration)

Three-phase protocol: **Triage** → **Launch** → **Synthesize**.

1. **Triage** — Detect project domains, profile input, score agents (base_score 0-3 + domain_boost 0-2 + project_bonus 0-1 + domain_agent 0-1), present roster for user approval
2. **Launch** — Dispatch Stage 1 agents in parallel, monitor completion, optionally expand to Stage 2 based on findings severity + adjacency scoring
3. **Synthesize** — Validate outputs, deduplicate findings, track convergence, compute verdict (safe/needs-changes/risky), generate findings.json + summary.md

See `docs/spec/README.md` for the full protocol specification.

## flux-research (Research Orchestration)

Three-phase protocol: **Triage** → **Launch** → **Synthesize**.

Uses a query-type affinity table to select research agents, dispatches in parallel, and synthesizes answers with source attribution. Progressive enhancement: uses Exa MCP for external research when available, falls back to Context7 + WebSearch.

## Domain Detection

LLM-based classification — a Haiku subagent reads README + build files + key source files and classifies the project into 11 known domains. Cached in `.claude/intersense.yaml` with `content_hash` for staleness detection. Staleness computed deterministically by `scripts/content-hash.py`. Domain detection scripts delegate to the intersense plugin (canonical location).

11 domains defined in intersense `config/domains/` (with local fallback at `config/flux-drive/domains/`). Each domain profile contains review criteria, agent specs, and Research Directives for external research agents.

## Agent Generation

`scripts/generate-agents.py` reads cached domain classification + domain profile markdown → writes `.claude/agents/fd-*.md` files. Deterministic template expansion (no LLM involvement). Three modes: `skip-existing`, `regenerate-stale` (checks `flux_gen_version` in frontmatter), `force`.

## Knowledge Lifecycle

Durable patterns from past reviews, managed by the **interknow** plugin:
- **Provenance tracking** — `independent` (re-discovered without prompting) vs `primed` (re-confirmed while in context)
- **Temporal decay** — entries not independently confirmed in 10 reviews are archived
- **Injection** — top 5 relevant entries injected into agent prompts via semantic search (qmd, served by interknow)
- **Compounding** — new patterns extracted from review findings and saved via interknow
