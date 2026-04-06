# Extension: AgentDropout

**Status:** Implemented (interflux v0.2.48+)
**Reference:** `phases/expansion.md § 2.2a.5`, `config/flux-drive/budget.yaml → dropout`

## Summary

Lightweight redundancy filter applied after Stage 1 completes. Prunes Stage 2 / expansion pool agents whose domains are already well-covered, saving tokens without losing coverage.

## Redundancy Scoring

Four signals (0.0–1.0 total):

| Signal | Weight | Trigger |
|--------|--------|---------|
| Domain convergence | 0.4 | Agent's primary domain already produced P0/P1 in Stage 1 |
| Adjacency saturation | 0.3 | All of agent's neighbors ran in Stage 1 |
| Finding density | 0.2 | ≥3 P0/P1 findings from adjacent agents |
| Low trust | 0.1 | Agent's trust multiplier < 0.5 |

## Decision

- Score ≥ threshold (0.6): **DROPPED** (unless exempt)
- Score < threshold: **RETAINED**
- Exempt agents (fd-safety, fd-correctness): **NEVER DROPPED**

## Skip Conditions

- Only 1 Stage 2 candidate
- Stage 1 produced zero findings
- `dropout.enabled` is false

## Override

User can select "Launch all Stage 2 anyway" in expansion decision — dropout is advisory, not a hard gate.

## Conformance

Optional extension. An implementation without AgentDropout dispatches all Stage 2 candidates.
