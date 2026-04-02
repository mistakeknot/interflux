# Phase 2.5: Reaction Round

**[review mode only]** — skip entirely in research mode.

Controlled by `config/flux-drive/reaction.yaml`. If `reaction_round.enabled` is false, skip to Phase 3.

### Step 2.5.0: Convergence Gate

**Step 2.5.0a: Collect stats.** Run `scripts/findings-helper.sh convergence {OUTPUT_DIR}`. Parse the tab-separated output: `overlap_ratio`, `total_findings`, `overlapping_findings`, `agent_count`. Also run `scripts/findings-helper.sh read-indexes {OUTPUT_DIR}` to collect the full findings index text.

**Step 2.5.0b: Fast-path guards.** Skip the haiku gate and proceed directly to Step 2.5.1 if ANY of:
- `agent_count == 0` — all Phase 2 agents failed. Emit skip event with `{"type":"skip","reason":"no_agents"}` and proceed to Phase 3.
- `agent_count == 1` — no peers to react to. Emit skip event with `{"type":"skip","reason":"single_agent"}` and proceed to Phase 3.
- `total_findings == 0` — nothing to react to. Emit skip event with `{"type":"skip","reason":"no_findings"}` and proceed to Phase 3.

**Step 2.5.0c: Haiku gate agent.** Dispatch a single Agent call (model: `haiku`) with this prompt:

````
You are the reaction-round gate. Decide whether a reaction round would add value.

## Agent Findings Indexes

{findings_index_text}

## Stats
- overlap_ratio: {overlap_ratio} (title-normalized, may miss semantic overlap)
- total_p0_p1_findings: {total_findings}
- overlapping_findings: {overlapping_findings}
- agent_count: {agent_count}

## Decision Criteria

Answer PROCEED if ANY of these are true:
1. **Implicit contradictions**: One agent's finding contradicts another's (e.g., agent A says "safe" but agent B found a P0 in the same area)
2. **Severity disagreement**: Agents flag the same issue at different severity levels
3. **Semantic overlap missed by stats**: Findings about the same underlying issue use different titles (overlap_ratio underestimates true convergence)
4. **Domain-expert blind spots**: An agent's finding falls squarely in another agent's domain but wasn't reported by them
5. **Low confidence signals**: Any agent's verdict is "needs-changes" or "risky" with few findings (under-reporting)

Answer SKIP if ALL of these are true:
1. Findings are complementary — each agent reviewed a different domain with no overlap
2. No implicit contradictions or severity disagreements exist
3. Agents that share a domain agree on what they found
4. Reactions would only produce "agree" stances with no new evidence

## Output Format (strict)

```
DECISION: PROCEED | SKIP
CONFIDENCE: high | medium | low
RATIONALE: [1-2 sentences]
```

Nothing else. No markdown headers, no explanations beyond the rationale.
````

Parse the response. If `DECISION: SKIP`, emit skip event with `{"type":"skip","reason":"haiku_gate","confidence":"{confidence}","rationale":"{rationale}","overlap_ratio":X,"agent_count":N,"finding_count":M}` via `_interspect_emit_reaction_dispatched()` (with `agents_dispatched: 0`). Also write `{OUTPUT_DIR}/reaction-skipped.json`. Proceed to Phase 3.

If `DECISION: PROCEED` or the haiku agent fails/times out, continue to Step 2.5.1.

**Cost:** ~1-2K tokens (~$0.002). The haiku gate replaces the formula-based threshold — no `effective_threshold` or `skip_if_convergence_above` computation needed.

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

**Sequencing constraint:** Step 2.5.2b MUST complete before Step 2.5.3 begins — do not parallelize. Fixative context depends on the complete findings set and Gini/novelty computation.

### Step 2.5.3-4: Build and Dispatch Reactions

For each Phase 2 agent with valid output: fill `config/flux-drive/reaction-prompt.md` template with `{agent_name}`, `{own_findings_index}`, `{peer_findings}` (topology-filtered), `{fixative_context}`, `{output_path}`. Skip agents with empty peer findings.

Dispatch as parallel Agent calls: model=`sonnet`, `run_in_background: true`, same `subagent_type` as original agent. Timeout: `timeout_seconds` from config (default: 60s). Output: `{agent-name}.reactions.md` or `.reactions.error.md`.

### Step 2.5.5: Report and Emit Evidence

`Reaction round: {N} dispatched, {M} produced, {K} empty, {E} errors/timeouts. Fixative: {status} ({N} injections)`.

**Emit `reaction-dispatched` evidence** via `_interspect_emit_reaction_dispatched()` with: `review_id` (OUTPUT_DIR basename), `input_path` (reviewed file), `agents_dispatched`, `reactions_produced`, `reactions_empty`, `reactions_errors`, `convergence_before` (overlap_ratio from Step 2.5.0), `agent_count` (Phase 2 agents), `fixative_injections` (count of fired injections from Step 2.5.2b).

Proceed to Phase 3.
