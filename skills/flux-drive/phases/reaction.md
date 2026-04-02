# Phase 2.5: Reaction Round

**[review mode only]** — skip entirely in research mode.

Controlled by `config/flux-drive/reaction.yaml`. If `reaction_round.enabled` is false, skip to Phase 3.

### Step 2.5.0: Convergence Gate

Run `scripts/findings-helper.sh convergence {OUTPUT_DIR}`. Parse the tab-separated output: `overlap_ratio`, `total_findings`, `overlapping_findings`, `agent_count`.

**Scaled threshold:** `effective_threshold = config.skip_if_convergence_above * (agent_count / 5)`. Cap at `config.skip_if_convergence_above` (never exceed original threshold). For N=2: threshold ~0.24 (reactions almost always fire). For N=5: threshold stays at 0.6. For N=8: threshold caps at 0.6.

**Peer-priming discount:** If `{OUTPUT_DIR}/peer-findings.jsonl` exists, read it. For each finding title in the overlap set, check if the first report timestamp in peer-findings.jsonl precedes a second agent's Findings Index entry. Discount peer-primed findings from the overlap count before computing `overlap_ratio`.

**Decision:** If `overlap_ratio > effective_threshold`, skip reaction round — emit an `interspect-reaction` event with context `{"type":"skip","overlap_ratio":X,"threshold":Y,"effective_threshold":Z,"agent_count":N,"finding_count":M}` via `_interspect_emit_reaction_dispatched()` (with `agents_dispatched: 0`). Also write `{OUTPUT_DIR}/reaction-skipped.json` with the same fields. Proceed to Phase 3.

Otherwise, continue to Step 2.5.1.

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
