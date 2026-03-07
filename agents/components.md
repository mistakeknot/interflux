# Components

## Review Agents (fd-*)

- 8 agents: 7 technical (auto-detect language) + 1 cognitive (fd-systems, documents only)
- YAML frontmatter: `name`, `description` (with `<example>` blocks), `model: sonnet`
- Each reads project CLAUDE.md/AGENTS.md for codebase-aware review
- Findings output uses the Findings Index contract: `SEVERITY | ID | "Section" | Title`
- Verdict: `safe | needs-changes | risky`
- **Cognitive agents** (fd-systems) are pre-filtered: only activate for `.md`/`.txt` document reviews (PRDs, brainstorms, plans, strategy docs), never for code or diffs. Use cognitive severity mapping: Blind Spot → P1, Missed Lens → P2, Consider Also → P3

## Research Agents

- 5 agents for different research tasks (best practices, framework docs, git history, learnings, repo analysis)
- Orchestrated by flux-research skill, not invoked directly
- Research Directives in domain profiles guide their search terms

## Commands

| Command | Description |
|---------|-------------|
| `/interflux:flux-drive` | Multi-agent document/code review |
| `/interflux:flux-research` | Multi-agent research with source attribution |
| `/interflux:flux-gen` | Generate project-specific review agents from detected domains |
| `/interflux:fetch-findings` | Inspect shared findings from parallel reviews |

## MCP Servers

| Server | Type | Purpose |
|--------|------|---------|
| **exa** | stdio | External web research via Exa API. Progressive enhancement — requires `EXA_API_KEY`. Falls back to Context7 + WebSearch if unavailable. |

**Note:** qmd MCP server (semantic search for knowledge) has moved to the **interknow** plugin.

## Protocol Specification

The flux-drive review protocol is formally specified in `docs/spec/` (flux-drive-spec 1.0.0). The spec extracts the abstract protocol from this reference implementation into standalone, framework-agnostic documents.

Three conformance levels:
- **Core** — 3-phase lifecycle, base scoring (0-4), staging, contracts, synthesis
- **Core + Domains** — adds domain detection, domain_boost/domain_agent_bonus scoring (0-7)
- **Core + Knowledge** — adds provenance-tracked review memory with temporal decay

See `docs/spec/README.md` for the full document index and reading order.
