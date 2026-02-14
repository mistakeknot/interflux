# Flux-Drive Protocol Specification

**Version:** 1.0.0
**Status:** Reference Architecture
**Reference Implementation:** [Interflux](https://github.com/interflux) (Claude Code plugin)

---

## What This Is

Flux-drive is a **domain-aware multi-agent review protocol** — an algorithm for triaging, launching, and synthesizing parallel specialized reviews of documents, codebases, and diffs. This specification extracts the abstract protocol from the Interflux reference implementation into standalone, framework-agnostic documents.

The protocol separates **static triage** (which agents are relevant?) from **dynamic expansion** (do early results justify more agents?) and uses **structured output contracts** to enable synthesis without parsing free-form prose.

## Audience

This spec serves two audiences:

- **AI tool developers** building multi-agent review systems — in any framework (Claude Code plugins, VS Code extensions, custom CLIs, API-based pipelines). The spec is framework-agnostic; Interflux-specific details are confined to "Interflux Reference" sections in each document.

- **Interflux/Clavain contributors** extending the existing system. The spec clarifies what the protocol requires vs. what the implementation happens to do, making it safer to modify without breaking the contract.

## Documents

### Core (Required)

| Document | Lines | Description |
|----------|-------|-------------|
| [core/protocol.md](core/protocol.md) | 595 | The 3-phase review lifecycle: triage → launch → synthesize. Input classification, workspace derivation, phase entry/exit conditions. |
| [core/scoring.md](core/scoring.md) | 375 | Agent selection algorithm: base_score (0-3) + domain_boost (0-2) + project_bonus (0-1) + domain_agent (0-1). Pre-filtering, dynamic slot ceiling, stage assignment. |
| [core/staging.md](core/staging.md) | 267 | Two-stage dispatch: Stage 1 (immediate, high-confidence) + Stage 2 (conditional, based on findings). Adjacency maps, expansion scoring, threshold decision. |
| [core/synthesis.md](core/synthesis.md) | 381 | Findings aggregation: index parsing, deduplication, convergence tracking, verdict computation, structured output (findings.json). |

### Contracts (Required)

| Document | Lines | Description |
|----------|-------|-------------|
| [contracts/findings-index.md](contracts/findings-index.md) | 133 | Structured agent output: `SEVERITY \| ID \| "Section" \| Title` + `Verdict: safe\|needs-changes\|risky`. The machine-readable interface between agents and orchestrator. |
| [contracts/completion-signal.md](contracts/completion-signal.md) | 107 | How agents signal completion: `.partial` → sentinel → rename. Timeout handling, error stubs, partial results. |

### Extensions (Optional)

| Document | Lines | Description |
|----------|-------|-------------|
| [extensions/domain-detection.md](extensions/domain-detection.md) | 168 | Project classification via weighted signal scoring (directories, files, frameworks, keywords). Multi-domain support, caching, staleness detection. |
| [extensions/knowledge-lifecycle.md](extensions/knowledge-lifecycle.md) | 141 | Review memory: knowledge accumulation, provenance tracking (independent vs. primed), temporal decay (10 reviews), sanitization. |

## Conformance Levels

An implementation can claim conformance at three levels:

### flux-drive-spec 1.0 Core

Implements:
- 3-phase lifecycle (triage → launch → synthesize)
- Agent scoring with `base_score` (0-3) and `project_bonus` (0-1) — minimum viable scoring (0-4 range)
- Dynamic slot ceiling (minimum 4, maximum 12)
- Two-stage dispatch with expansion decision
- Findings Index output format
- Completion signaling protocol
- Deduplication and verdict computation

Core implementations MAY skip `domain_boost` and `domain_agent_bonus` (both require domain detection). The full scoring formula in [core/scoring.md](core/scoring.md) documents all components; Core conformance requires only `base_score` + `project_bonus`.

### flux-drive-spec 1.0 Core + Domains

Additionally implements:
- Weighted signal scoring for domain detection
- Multi-domain classification
- `domain_boost` (0-2) and `domain_agent_bonus` (0-1) scoring components — extends scoring range to 0-7
- Domain-specific criteria injection

### flux-drive-spec 1.0 Core + Knowledge

Additionally implements:
- Knowledge entry format with provenance tracking
- Independent vs. primed confirmation distinction
- Temporal decay (configurable review count)
- Knowledge retrieval and injection into agent prompts

## Versioning

This spec uses [Semantic Versioning](https://semver.org/):

- **Major** (2.0, 3.0): Breaking changes to core protocol or contracts
- **Minor** (1.1, 1.2): New extensions, non-breaking additions to core
- **Patch** (1.0.1, 1.0.2): Clarifications, typo fixes, example additions

The spec version is independent of Interflux's version. An implementation conforming to "flux-drive-spec 1.0" works with any Interflux version that also conforms to 1.0.

## Reading Order

For newcomers, we recommend:

1. **This README** — understand what flux-drive is and the conformance levels
2. **[core/protocol.md](core/protocol.md)** — the 3-phase lifecycle (the big picture)
3. **[contracts/findings-index.md](contracts/findings-index.md)** — the output format (the interface)
4. **[contracts/completion-signal.md](contracts/completion-signal.md)** — how agents signal done
5. **[core/scoring.md](core/scoring.md)** — how agents are selected
6. **[core/staging.md](core/staging.md)** — how dispatch adapts to findings
7. **[core/synthesis.md](core/synthesis.md)** — how results are aggregated
8. **[extensions/domain-detection.md](extensions/domain-detection.md)** — optional domain awareness
9. **[extensions/knowledge-lifecycle.md](extensions/knowledge-lifecycle.md)** — optional review memory

## Directory Structure

```
docs/spec/
├── README.md                            # This file
├── core/
│   ├── protocol.md                      # 3-phase lifecycle
│   ├── scoring.md                       # Agent selection algorithm
│   ├── staging.md                       # Stage expansion logic
│   └── synthesis.md                     # Findings aggregation
├── extensions/
│   ├── domain-detection.md              # Domain signal scoring
│   └── knowledge-lifecycle.md           # Knowledge decay + accumulation
└── contracts/
    ├── findings-index.md                # Agent output format
    └── completion-signal.md             # Completion signaling
```
