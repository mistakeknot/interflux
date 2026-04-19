# interflux

Multi-agent review, research, and model evaluation engine for Claude Code.

## What this does

interflux is the review infrastructure behind Clavain's `/flux-drive` and `/flux-research` commands. Point it at a document or codebase and it runs a scored triage to figure out which domain agents are relevant, slices the content so each agent only sees what it needs, injects project-specific knowledge, and synthesizes the results.

There are 12 review agents (7 technical: architecture, safety, correctness, performance, quality, game design, user/product; 5 cognitive: systems thinking, decision quality, human systems, adaptive capacity, sensemaking) and 5 research agents (best practices, framework docs, git history, learnings, repo research). The triage step means you don't pay for all of them on every review — only the relevant ones fire.

The engine also powers `flux-research`, which dispatches research agents in parallel and synthesizes their findings, and `flux-review`, which generates review agents across a spectrum of semantic distance for deep analysis.

### FluxBench

FluxBench is the closed-loop model evaluation system. It scores candidate models against ground-truth test fixtures, qualifies them for production use, monitors for quality drift, and manages a challenger slot for evaluating new models alongside the existing fleet.

The pipeline: `qualify → score → sync → drift → challenger`. Each script is independently testable and connected through shared contracts — `qualification_run_id` flows through the entire pipeline, `qualified_baseline` is write-once to prevent ratchet erosion, and concurrent writes are protected by flock (fd 200 for JSONL, fd 201 for registry).

## Installation

First, add the [interagency marketplace](https://github.com/mistakeknot/interagency-marketplace) (one-time setup):

```bash
/plugin marketplace add mistakeknot/interagency-marketplace
```

Then install the plugin:

```bash
/plugin install interflux
```

## Usage

Review a document or codebase:

```
/flux-drive docs/plans/my-feature.md
```

Research a topic with parallel agents:

```
/flux-research "best practices for SQLite WAL mode in Go CLI tools"
```

Deep multi-track review (adjacent → orthogonal → esoteric):

```
/flux-review docs/brainstorms/my-idea.md
```

Generate project-specific review agents:

```
/flux-gen
```

Explore ideas through progressively distant knowledge domains:

```
/flux-explore "agent orchestration patterns"
```

Run FluxBench qualification against test fixtures:

```bash
scripts/fluxbench-qualify.sh <model-slug> --mock --fixtures-dir tests/fixtures/qualification/
```

## Architecture

```
agents/
  review/          12 review agents (fd-architecture, fd-safety, fd-correctness, ...)
  research/        5 research agents (best-practices, framework-docs, git-history, ...)
  fluxbench-discover.md   Weekly model discovery agent spec
skills/            flux-drive, flux-research
commands/          7 commands (flux-drive, flux-research, flux-review, flux-gen,
                     flux-explore, flux-agent, fetch-findings)
config/flux-drive/
  budget.yaml              Token budgets, agent dropout, challenger slots
  agent-roles.yaml         Role → model tier mapping (planner/reviewer/editor/checker/challenger)
  model-registry.yaml      Candidate models, FluxBench scores, qualified baselines
  fluxbench-metrics.yaml   9 metric definitions (5 core gates + 4 extended)
  fluxbench-thresholds.yaml  Calibrated thresholds (overrides metric defaults)
  domains/                 12 domain profiles with research directives
  discourse-*.yaml         4 discourse modes (fixative, Lorenzen, Sawyer, topology)
scripts/
  fluxbench-score.sh       Scoring engine — 9 metrics, bipartite finding matching, flock writes
  fluxbench-calibrate.sh   Derives thresholds from fixture runs (p25 conservative)
  fluxbench-drift.sh       Drift detection with hysteresis and correlated-drift protection
  fluxbench-sync.sh        Store-and-forward sync to AgMoDB (idempotent, no git commits)
  fluxbench-qualify.sh     Qualification runner — fixtures → score → promote/reject
  fluxbench-challenger.sh  Challenger slot lifecycle (select, evaluate, status)
  discover-models.sh       Model discovery via interrank/AgMoDB
  estimate-costs.sh        Token cost estimation with slicing discount
  generate-agents.py       Project-specific agent generation from domain detection
  flux-agent.py            Agent dispatch engine
tests/
  test_fluxbench_*.bats    24 bats tests across 5 test files
  fixtures/qualification/  5 ground-truth fixtures (null-check, SQL injection, naming,
                             race condition, API design)
  test-budget.sh           Budget config validation
  test-findings-flow.sh    Finding sharing flow tests
hooks/
  session-start.sh         Budget signal reading + FluxBench model awareness
docs/spec/                 flux-drive protocol specification (versioned independently)
```

One MCP server: `exa` for web search (progressive enhancement — falls back to Context7 + WebSearch when `EXA_API_KEY` isn't set).

## Naming doctrine

- `inter*` names are canonical Interverse / Sylveste-native capabilities.
- Hermes-specific adapters over those capabilities may use `athen*` names when they add substantive Hermes-native orchestration, prompting, synthesis, or workflow opinionation.
- For the current doctrine note and rationale, see `docs/research/interverse-athenverse-doctrine.md`.

## FluxBench metrics

5 core gates (all must pass for qualification):

| Metric | Type | Default threshold |
|--------|------|-------------------|
| Format compliance | Binary gate | 0.95 |
| Finding recall (severity-weighted) | Weighted score | 0.60 |
| False positive rate | Rate (lower is better) | 0.20 |
| Severity accuracy (±1 level) | Score | 0.70 |
| Persona adherence | LLM-judged | 0.60 |

4 extended metrics (informational, used for routing): instruction compliance, disagreement rate, latency p50, token efficiency.

## Model lifecycle

```
candidate → qualifying → auto-qualified → qualified → active → retired
                              ↓
                          challenger (evaluation slot)
```

- **discover-models.sh** queries interrank for new candidates
- **fluxbench-qualify.sh** runs candidates against fixtures, promotes on all-gate pass
- **qualified_baseline** is frozen at qualification time (write-once)
- **fluxbench-drift.sh** compares shadow runs against baseline, flags regression >15%
- **fluxbench-challenger.sh** manages a single challenger slot with early-exit fast-track
- Correlated drift (≥50% of fleet) triggers baseline-shift alert instead of mass demotion

## Design decisions

- Technical agents auto-detect language from the code under review
- Cognitive agents review documents only (plans, PRDs, strategies)
- Triage scoring prevents unnecessary agent launches — AgentDropout prunes redundant agents
- Role-based model routing: safety/correctness never downgrade below Sonnet
- Budget enforcement is soft by default (warn + offer override)
- FluxBench data passes to inline Python via environment variables, never string interpolation
- Registry writes use atomic swap (cp → modify → validate → mv) under flock
- The full protocol spec lives in `docs/spec/` and is versioned independently
