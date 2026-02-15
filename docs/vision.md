# interflux — Vision and Philosophy

## What Interflux Is

Interflux is Clavain’s multi-agent review and research engine, extracted once those orchestration patterns stabilized in production use. It turns "run a bunch of agents and hope" into a protocol: select the right specialists, dispatch them deterministically, synthesize structured findings, and produce auditable artifacts.

The plugin has three commitments:

- **Review rigor**: structured triage, staged launch, and deterministic synthesis via `findings.json`.
- **Research depth on demand**: lightweight orchestration for external/internal synthesis when single-agent research is too narrow.
- **Compounding quality**: knowledge injection and persistent criteria from prior successful findings.

Its core productized artifacts are two skills (`flux-drive`, `flux-research`), two MCP servers (`qmd`, `exa`), and a protocol spec (`docs/spec`) that any implementation can adopt.

## Core Convictions

### 1. Contracts beat clever prompts
Subagents are easy to scale only when the interfaces are explicit. Findings Indexes, completion sentinels, and completion/error conventions are non-negotiable because they let 7+ agents be measured and combined safely.

### 2. Relevance first, breadth second
Launching all agents is a false optimization. Interflux filters, scores, and gates work by relevance so effort follows risk, not habit.

### 3. Evidence over opinion
Each finding should be traceable to files, hunks, and context. Without location and rationale, confidence cannot be shared across agents, models, or runs.

### 4. Cost is a first-class design axis
Review depth is staged by default: fast Stage 1, conditional Stage 2. Automation is constrained by explicit user approval at expansion points.

### 5. Learning is valuable only with provenance
Knowledge entries are useful only if we can distinguish independent rediscovery from primed recall. Otherwise we just reinforce prior assumptions.

## Scope

Interflux explicitly covers:

- Multi-agent review of plans, docs, diffs, repos (`/interflux:flux-drive`)
- Multi-agent research for onboarding, best-practice, code-history, and framework questions (`/interflux:flux-research`)
- Project-specific agent generation from detected domains (`/interflux:flux-gen`)
- Spec-driven coordination primitives reusable in Clavain and external hosts

Interflux explicitly does **not**:

- Provide UI dashboards (CLI + artifact-first summaries are the surface)
- Define a new LLM framework
- Replace human judgment on priority, product direction, or risk acceptance

## What Interflux Is Not

- **Not a monolith.** It is a host-level orchestrator with fixed contracts.
- **Not an IDE plugin.** It runs in Claude Code’s plugin/runtime model.
- **Not generic code review.** It is opinionated: review profiles, staged dispatch, and triage-driven selection.

## Where It Fits in the Constellation

Interflux is the execution layer for high-confidence review and research:

- `interphase` defines when workflows run.
- `interlock` and `interwatch` feed operational context.
- `interpath` and `interline` consume review artifacts.

Interflux is one of the earliest proven companions: extracted from Clavain usage patterns and now stable enough to serve as a reference implementation for multi-agent protocol design.

## 2026-02-15 Context

Version `0.2.0` aligns with a companion-class plugin shape: 2 skills, 3 commands, 12 agents total (7 review + 5 research + 0 hidden), and 2 MCP servers.

Current focus is to continue tightening runtime correctness, confidence reporting, and roadmap execution discipline while preserving the proven 3-level protocol (`core`/`core+domains`/`core+knowledge`).
