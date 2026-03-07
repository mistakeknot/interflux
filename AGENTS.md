# interflux — Development Guide

Multi-agent review and research engine for Claude Code. Companion plugin for [Clavain](https://github.com/mistakeknot/Clavain).

## Canonical References
1. [`PHILOSOPHY.md`](../../PHILOSOPHY.md) — direction for ideation and planning decisions.
2. `CLAUDE.md` — implementation details, architecture, testing, and release workflow.

## Quick Reference

| Item | Value |
|------|-------|
| Repo | `https://github.com/mistakeknot/interflux` |
| Namespace | `interflux:` |
| Manifest | `.claude-plugin/plugin.json` |
| Components | 17 agents (12 review + 5 research), 4 commands, 2 skills, 2 MCP servers, 1 hook |
| License | MIT |

### Release Workflow

- Run `scripts/bump-version.sh <version>` (or `/interpub:release <version>` in Claude Code) for any released changes.
- It updates `.claude-plugin/plugin.json`, `infra/marketplace/.claude-plugin/marketplace.json`, and discovered versioned artifacts.
- The command commits and pushes both plugin and marketplace repos atomically.
- Use patch bumps for routine user-facing updates (`0.2.x -> 0.2.x+1`).

## Topic Guides

| Topic | File | Covers |
|-------|------|--------|
| Architecture | [agents/architecture.md](agents/architecture.md) | Directory layout, flux-drive/flux-research orchestration, domain detection, agent generation, knowledge lifecycle |
| Components | [agents/components.md](agents/components.md) | Review agents (fd-*), research agents, commands, MCP servers, protocol specification |
| Finding Sharing | [agents/finding-sharing.md](agents/finding-sharing.md) | Peer-findings JSONL, severity levels, helper script, synthesis |
| Testing | [agents/testing.md](agents/testing.md) | Structural test suites, validation checklist |
| Measurement | [agents/measurement.md](agents/measurement.md) | Token types, cost types, scopes, budget configuration |
| Dual-Mode | [agents/dual-mode.md](agents/dual-mode.md) | Standalone vs integrated operation, interbase SDK, known constraints |

## Philosophy Alignment Protocol
Review [`PHILOSOPHY.md`](../../PHILOSOPHY.md) during:
- Intake/scoping
- Brainstorming
- Planning
- Execution kickoff
- Review/gates
- Handoff/retrospective

For brainstorming/planning outputs, add two short lines:
- **Alignment:** one sentence on how the proposal supports the module's purpose within Demarch's philosophy.
- **Conflict/Risk:** one sentence on any tension with philosophy (or 'none').

If a high-value change conflicts with philosophy, either:
- adjust the plan to align, or
- create follow-up work to update `PHILOSOPHY.md` explicitly.
