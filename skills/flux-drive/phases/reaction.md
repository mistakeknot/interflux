# Phase 2.5: Reaction Round

**[review mode only]** — skip entirely in research mode.

This phase is optional and controlled by `config/flux-drive/reaction.yaml`. If `reaction_round.enabled` is `false` (or the current mode is disabled via `mode_overrides`), skip this phase entirely and proceed to Phase 3.

### Step 2.5.0: Convergence Gate

Before dispatching reactions, check whether peer review adds value:

1. Read the Findings Indexes from all Phase 2 agent outputs (use `scripts/findings-helper.sh read-indexes {OUTPUT_DIR}`).
2. Count P0/P1 findings. For each, check how many agents reported it (by matching Finding ID or fuzzy title match with 3+ shared keywords).
3. Compute `overlap_ratio = findings_with_2plus_agents / total_p0_p1_findings`.
4. If `overlap_ratio > skip_if_convergence_above` (default: 0.6), skip the reaction round:
   ```
   Reaction round skipped: {overlap_ratio*100}% P0/P1 convergence exceeds threshold ({skip_if_convergence_above*100}%). Secondary processing adds noise on homogeneous substrate.
   ```
5. Proceed to Phase 3.

If convergence is below threshold, continue to Step 2.5.1.

### Step 2.5.1: Cleanup Stale Reactions

Delete any `*.reactions.md` and `*.reactions.error.md` files from `{OUTPUT_DIR}` left over from previous runs:

```bash
rm -f {OUTPUT_DIR}/*.reactions.md {OUTPUT_DIR}/*.reactions.error.md
```

### Step 2.5.2: Collect Findings Indexes

For each Phase 2 agent output file (`{OUTPUT_DIR}/{agent-name}.md`):

1. Extract the Findings Index (between `### Findings Index` and the next `###` heading or end of index block — typically the first ~30 lines).
2. Parse each index line: `- SEVERITY | ID | "Section" | Title`
3. Filter to severities in `severity_filter` config (default: P0, P1).
4. If `severity_filter_p2_light` is true, also collect P2 findings (these get lighter treatment in the prompt).

Build a combined peer findings summary for each agent, **excluding that agent's own findings**.

### Step 2.5.3: Build Per-Agent Reaction Prompts

For each Phase 2 agent that produced valid output:

1. Load the reaction prompt template from `config/flux-drive/reaction-prompt.md`.
2. Fill template slots:
   - `{agent_name}` — the reacting agent's name
   - `{agent_description}` — from agent roster or agent file header
   - `{own_findings_index}` — this agent's own Findings Index (for self-comparison)
   - `{peer_findings}` — combined P0/P1 (and optionally P2) findings from all OTHER agents
   - `{output_path}` — `{OUTPUT_DIR}/{agent-name}.reactions.md`
3. If `{peer_findings}` is empty for this agent (no other agents found P0/P1 issues), skip this agent — no reaction needed.

### Step 2.5.4: Dispatch Reaction Agents

Dispatch all reaction prompts as parallel Agent calls:

- **Model:** `sonnet` (from config, overridable)
- **Background:** `run_in_background: true`
- **Subagent type:** Use the same `subagent_type` as the original Phase 2 agent (so fd-safety reacts as fd-safety, etc.)

Each agent must write either:
- `{agent-name}.reactions.md` — structured reaction output per the template contract
- `{agent-name}.reactions.error.md` — if the agent encountered an error

**Timeout contract:** Each agent operates within the Phase 2 per-agent timeout (from `config/flux-drive/reaction.yaml` `timeout_seconds`, default: 60s). Proceed to Phase 3 with whatever files exist after timeout. Do not block on stragglers.

### Step 2.5.5: Report

After all agents complete (or timeout):

```
Reaction round: {N} agents dispatched, {M} reactions produced, {K} empty (no relevant peer findings), {E} errors/timeouts.
```

Proceed to Phase 3 (Synthesize). The synthesis agent reads `.reactions.md` files separately from agent output files.
