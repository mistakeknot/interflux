---
name: fluxbench-discover
description: Weekly model discovery and auto-qualification agent
schedule: weekly
autonomy: auto-qualified (requires operator confirmation for full promotion)
---

# FluxBench Discovery Agent

## Purpose
Discover new model candidates via interrank and auto-qualify them against FluxBench test fixtures.

## Workflow
1. Run `scripts/discover-models.sh` to generate interrank queries
2. Execute MCP calls: `recommend_model` for each tier query, `cost_leaderboard` for coding+agentic
3. For each new candidate not in model-registry.yaml:
   a. Add as `status: candidate`
   b. Run `scripts/fluxbench-qualify.sh <model_slug>`
   c. If passes: promote to `auto-qualified`, create bead
   d. If fails: mark failure reason, leave as `candidate`
4. Budget ceiling: max 5 candidates per run (configurable in model-registry.yaml)
5. Write summary to stdout for operator awareness

## Tools Required
- interrank MCP: recommend_model, cost_leaderboard
- File read/write: model-registry.yaml, fluxbench-results.jsonl
- Beads: bd create (for qualified candidates)
