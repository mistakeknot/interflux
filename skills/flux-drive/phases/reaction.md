# Phase 2.5: Reaction Round

**[review mode only]** — skip entirely in research mode.

Controlled by `config/flux-drive/reaction.yaml`. If `reaction_round.enabled` is false, skip to Phase 3.

### Step 2.5.0: Convergence Gate

Read Findings Indexes via `scripts/findings-helper.sh read-indexes {OUTPUT_DIR}`. Count P0/P1 findings, compute `overlap_ratio = findings_with_2plus_agents / total_p0_p1_findings`. If `overlap_ratio > skip_if_convergence_above` (default: 0.6), skip reaction round and proceed to Phase 3.

### Step 2.5.1: Cleanup

`rm -f {OUTPUT_DIR}/*.reactions.md {OUTPUT_DIR}/*.reactions.error.md`

### Step 2.5.2: Collect Findings Indexes

Extract Findings Index from each agent output. Parse `- SEVERITY | ID | "Section" | Title`. Filter to `severity_filter` (default: P0, P1; optionally P2 with `severity_filter_p2_light`). Retain full unfiltered collection for fixative and synthesis.

### Step 2.5.2a: Topology-Aware Peer Visibility

Read `config/flux-drive/discourse-topology.yaml`. If missing/disabled, use fully-connected (all agents see all findings).

If enabled: read `agent-roles.yaml`, map `agent_name → role`. Visibility rules: same role → `full` (complete index block), adjacent roles → `summary` (index lines only), otherwise → `none`. Isolation fallback (SCT-02): zero visible peers → use `fallback_on_isolation` level from all peers.

Full unfiltered findings preserved for fixative (Step 2.5.2b) — topology only affects per-agent reaction prompts.

### Step 2.5.2b: Discourse Fixative Health Check

Read `config/flux-drive/discourse-fixative.yaml`. If missing/disabled, set `fixative_context` to empty.

If enabled, compute from all-severity findings:
- **Participation Gini** (0=equal, 1=dominated). Trigger: `gini > participation_gini_above` → `imbalance`
- **Novelty estimate** (1 - overlap_ratio across all findings). Trigger: `novelty < novelty_estimate_below` → `convergence`
- **Drift**: always fires (unconditional). **Collapse**: fires if imbalance AND convergence both trigger.

Concatenate fired injections into `fixative_context`.

### Step 2.5.3-4: Build and Dispatch Reactions

For each Phase 2 agent with valid output: fill `config/flux-drive/reaction-prompt.md` template with `{agent_name}`, `{own_findings_index}`, `{peer_findings}` (topology-filtered), `{fixative_context}`, `{output_path}`. Skip agents with empty peer findings.

Dispatch as parallel Agent calls: model=`sonnet`, `run_in_background: true`, same `subagent_type` as original agent. Timeout: `timeout_seconds` from config (default: 60s). Output: `{agent-name}.reactions.md` or `.reactions.error.md`.

### Step 2.5.5: Report

`Reaction round: {N} dispatched, {M} produced, {K} empty, {E} errors/timeouts. Fixative: {status} ({N} injections)`. Proceed to Phase 3.
