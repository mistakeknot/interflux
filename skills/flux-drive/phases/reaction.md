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

**Retain the full, unfiltered findings collection** — this is used by the convergence gate (Step 2.5.0, already computed), the fixative (Step 2.5.2b), and synthesis. Topology filtering (Step 2.5.2a) produces per-agent filtered views for reaction prompts only.

### Step 2.5.2a: Topology-Aware Peer Visibility

Read `config/flux-drive/discourse-topology.yaml`. If the file does not exist, cannot be parsed, or `topology.enabled` is false, skip this step — use fully-connected behavior (each agent sees ALL other agents' findings).

If topology is enabled:

1. **Read agent role assignments** from `config/flux-drive/agent-roles.yaml`. Build a map: `agent_name → role`. Agents not in the map get `default_role` from topology config (default: `editor`).

2. **For each reacting agent**, determine visibility for every other agent:
   - Look up both agents' roles
   - If same role → `full` (complete Findings Index block)
   - If roles are in each other's `adjacency` list → `summary` (parsed index line only: `- SEVERITY | ID | Title`)
   - Otherwise → `none` (excluded)

3. **Isolation fallback** (SCT-02 fix): If an agent has zero visible peers after filtering (all other agents are `none` visibility), fall back to `fallback_on_isolation` level (default: `summary`) from ALL peers. This prevents silent no-op when only non-adjacent agents are dispatched. Log: `Topology fallback: {agent_name} isolated, using summary from all peers`.

4. **Build per-agent peer findings:**
   - **Full:** Include the complete Findings Index block
   - **Summary:** Include only parsed index lines (one line per finding)
   - **None:** Exclude entirely

5. **Log topology:**
   ```
   Topology: domain-aware ({N} agents, {full_pairs} full, {summary_pairs} summary, {excluded_pairs} excluded, {isolated} isolated→fallback)
   ```

The per-agent filtered `{peer_findings}` is passed to Step 2.5.3 for template filling.

**Important:** The full, unfiltered findings collection from Step 2.5.2 is preserved and passed to Step 2.5.2b (fixative) unchanged. The fixative always sees the complete discourse state — topology filtering does NOT affect health metrics. This is intentional: the fixative monitors global health, while topology constrains local visibility.

### Step 2.5.2b: Discourse Fixative Health Check

Read `config/flux-drive/discourse-fixative.yaml`. If the file does not exist or cannot be parsed, treat the fixative as disabled — skip this step entirely and set `fixative_context` to empty.

If `fixative.enabled` is true:

1. **Compute approximate health metrics** from the Findings Indexes already collected in Step 2.5.2. Include ALL severities (P0, P1, and P2 when `severity_filter_p2_light` is true) — not just P0/P1.

   - **Participation Gini:** Count total findings per agent from all collected indexes. Compute Gini coefficient (0 = equal, 1 = one agent dominates). If ≤ 1 agent, Gini = 0.
   - **Novelty estimate:** Compute overlap across all findings (not just P0/P1): count findings whose title matches (3+ shared keywords) across 2+ agents, divide by total findings. `novelty_estimate = 1 - all_findings_overlap_ratio`. This is a pre-synthesis approximation — the authoritative metric comes from synthesis Step 6.6.

2. **Check triggers** against thresholds from the config:
   - `gini > participation_gini_above` → fire `imbalance` injection
   - `novelty_estimate < novelty_estimate_below` → fire `convergence` injection
   - `drift_unconditional` is true → always fire `drift` injection (evidence-anchoring cannot be estimated pre-synthesis)
   - If `imbalance` AND `convergence` both fire (2-of-2 strongest signals) → also fire `collapse` injection (compound degradation onset)

3. **Build fixative context string.** If any injections fired, concatenate them separated by blank lines. If no triggers fired (only drift is unconditional), `fixative_context` contains only the drift note.

4. **Log fixative activity:**
   ```
   Fixative: {active|inactive} ({N} injections: {injection_names})
   ```
   If inactive (only drift fired): `Fixative: drift-only`

5. **Pass `fixative_context` to Step 2.5.3** for template slot filling.

### Step 2.5.3: Build Per-Agent Reaction Prompts

For each Phase 2 agent that produced valid output:

1. Load the reaction prompt template from `config/flux-drive/reaction-prompt.md`.
2. Fill template slots:
   - `{agent_name}` — the reacting agent's name
   - `{agent_description}` — from agent roster or agent file header
   - `{own_findings_index}` — this agent's own Findings Index (for self-comparison)
   - `{peer_findings}` — combined P0/P1 (and optionally P2) findings from all OTHER agents
   - `{output_path}` — `{OUTPUT_DIR}/{agent-name}.reactions.md`
   - `{fixative_context}` — discourse fixative injections from Step 2.5.2b (empty string if fixative disabled or no triggers fired beyond drift)
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
Fixative: {active|inactive|drift-only} ({N} injections)
```

Proceed to Phase 3 (Synthesize). The synthesis agent reads `.reactions.md` files separately from agent output files.
