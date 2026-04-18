# interflux

> See `AGENTS.md` for full development guide.

## Overview

Multi-agent review and research engine — 17 agents (12 review + 5 research), 7 commands, 1 skill (unified flux-drive with review/research modes), 2 MCP servers (exa, openrouter-dispatch). Companion plugin for Clavain. Provides scored triage, LLM-based domain classification, content slicing, knowledge injection, parallel multi-agent research, and quality-tiered agent lifecycle management.

## Protocol Specification

The flux-drive review protocol is documented in `docs/spec/` (flux-drive-spec 1.0.0). 9 documents covering the 3-phase lifecycle, scoring algorithm, staging dispatch, synthesis, contracts, and extensions. See `docs/spec/README.md` for reading order and conformance levels.

## Quick Commands

```bash
# Test locally
claude --plugin-dir /root/projects/Interverse/plugins/interflux

# Validate structure
ls skills/*/SKILL.md | wc -l          # Should be 1 (flux-drive; flux-research skill removed in v0.2.61)
ls agents/review/*.md | wc -l         # Should be 12
ls agents/research/*.md | wc -l       # Should be 5
ls commands/*.md | wc -l              # Should be 7
python3 -c "import json; d=json.load(open('.claude-plugin/plugin.json')); print(list(d['mcpServers'].keys()))"  # ['exa']
grep -l '## Research Directives' config/flux-drive/domains/*.md | wc -l  # Should be 11
python3 -c "import json; json.load(open('.claude-plugin/plugin.json'))"  # Manifest check
```

## Design Decisions (Do Not Re-Ask)

- Namespace: `interflux:` (companion to Clavain)
- 12 review agents: 7 technical (fd-architecture, fd-safety, fd-correctness, fd-quality, fd-user-product, fd-performance, fd-game-design) + 5 cognitive (fd-systems, fd-decisions, fd-people, fd-resilience, fd-perception) — technical agents auto-detect language, cognitive agents review documents only
- 5 research agents (best-practices-researcher, framework-docs-researcher, git-history-analyzer, learnings-researcher, repo-research-analyst) — orchestrated by flux-research
- Phase tracking is the **caller's** responsibility — interflux commands do not source lib-gates.sh
- Knowledge compounding delegated to interknow plugin (was `config/flux-drive/knowledge/`)
- qmd MCP server moved to interknow plugin (semantic search for knowledge entries)
- Exa MCP server is a progressive enhancement — if `EXA_API_KEY` not set, agents fall back to Context7 + WebSearch
- Research Directives in domain profiles guide external agents (best-practices, framework-docs) with domain-specific search terms
