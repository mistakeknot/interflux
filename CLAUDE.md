# interflux

> See `AGENTS.md` for full development guide.

## Overview

Multi-agent review and research engine — 17 agents (12 review + 5 research), 3 commands, 2 skills, 2 MCP servers. Companion plugin for Clavain. Provides scored triage, domain detection, content slicing, knowledge injection, and parallel multi-agent research.

## Protocol Specification

The flux-drive review protocol is documented in `docs/spec/` (flux-drive-spec 1.0.0). 9 documents covering the 3-phase lifecycle, scoring algorithm, staging dispatch, synthesis, contracts, and extensions. See `docs/spec/README.md` for reading order and conformance levels.

## Quick Commands

```bash
# Test locally
claude --plugin-dir /root/projects/Interverse/plugins/interflux

# Validate structure
ls skills/*/SKILL.md | wc -l          # Should be 2
ls agents/review/*.md | wc -l         # Should be 12
ls agents/research/*.md | wc -l       # Should be 5
ls commands/*.md | wc -l              # Should be 3
python3 -c "import json; d=json.load(open('.claude-plugin/plugin.json')); print(list(d['mcpServers'].keys()))"  # ['qmd', 'exa']
grep -l '## Research Directives' config/flux-drive/domains/*.md | wc -l  # Should be 11
python3 -c "import json; json.load(open('.claude-plugin/plugin.json'))"  # Manifest check
```

## Design Decisions (Do Not Re-Ask)

- Namespace: `interflux:` (companion to Clavain)
- 12 review agents: 7 technical (fd-architecture, fd-safety, fd-correctness, fd-quality, fd-user-product, fd-performance, fd-game-design) + 5 cognitive (fd-systems, fd-decisions, fd-people, fd-resilience, fd-perception) — technical agents auto-detect language, cognitive agents review documents only
- 5 research agents (best-practices-researcher, framework-docs-researcher, git-history-analyzer, learnings-researcher, repo-research-analyst) — orchestrated by flux-research
- Phase tracking is the **caller's** responsibility — interflux commands do not source lib-gates.sh
- Knowledge compounding writes to interflux's `config/flux-drive/knowledge/` directory
- qmd MCP server provides semantic search for project documentation
- Exa MCP server is a progressive enhancement — if `EXA_API_KEY` not set, agents fall back to Context7 + WebSearch
- Research Directives in domain profiles guide external agents (best-practices, framework-docs) with domain-specific search terms
