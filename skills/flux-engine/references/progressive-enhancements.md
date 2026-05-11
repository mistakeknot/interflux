# Progressive Enhancement Steps (Launch Phase)

These steps are OPTIONAL — each activates only when its corresponding system is available. If unavailable, skip silently. None of these are gates.

---

## Step 2.1: Knowledge Context Retrieval

**Activates when:** qmd MCP tool (via interknow plugin) is available.

For each selected agent, retrieve relevant knowledge entries:
1. Combine the agent's domain keywords with the document summary from Phase 1
2. Use qmd MCP tool to search:
   ```
   Tool: mcp__plugin_interknow_qmd__vsearch
   Parameters:
     collection: "interknow"
     query: "{agent domain} {document summary keywords}"
     path: "config/knowledge/"
     limit: 5
   ```
3. Format results as a knowledge context block for the agent prompt

**Domain keywords by agent:**
| Agent | Domain keywords |
|-------|----------------|
| fd-architecture | architecture boundaries coupling patterns complexity |
| fd-safety | security threats credentials deployment rollback trust |
| fd-correctness | data integrity transactions races concurrency async |
| fd-quality | naming conventions testing code quality style idioms |
| fd-user-product | user experience flows UX value proposition scope |
| fd-performance | performance bottlenecks rendering memory scaling |
| fd-game-design | game balance pacing player psychology feedback loops emergent behavior |

**Cap**: 5 entries per agent. **Fallback**: Skip entirely if qmd unavailable or errors. **Pipelining**: Start queries before dispatch; inject when both ready.

---

## Step 2.1a: Domain-Specific Review Criteria [review only]

**Activates when:** Step 1.0.1 detected project domains (not "none").

For each detected domain, load `${CLAUDE_PLUGIN_ROOT}/config/flux-drive/domains/{domain-name}.md`. Extract per-agent `### fd-{agent-name}` subsections under `## Injection Criteria`. Store as `{DOMAIN_CONTEXT}` per agent.

**Multi-domain**: Inject from ALL detected domains (cap 3), ordered by confidence. Skip missing profiles silently.

---

## Step 2.1d: Overlay Loading (interspect Type 1) [review only]

**Activates when:** interspect overlays directory exists for the project.

For each selected agent:
1. Source `lib-interspect.sh`, call `_interspect_read_overlays "{agent-name}"`
2. Re-sanitize: `_interspect_sanitize "$content" 2000` (defense-in-depth)
3. Budget: `_interspect_count_overlay_tokens "$content"` — cap 500 tokens per agent
4. Store as `{OVERLAY_CONTEXT}` for the agent prompt

**Fallback**: Skip silently if overlays directory doesn't exist or no active overlays.

---

## Step 2.1e: Trust Multiplier (intertrust feedback) [review only]

**Activates when:** lib-trust.sh found in plugin cache.

```bash
TRUST_PLUGIN=$(find ~/.claude/plugins/cache -path "*/intertrust/*/hooks/lib-trust.sh" 2>/dev/null | head -1)
[[ -z "$TRUST_PLUGIN" ]] && TRUST_PLUGIN=$(find ~/.claude/plugins/cache -path "*/interspect/*/hooks/lib-trust.sh" 2>/dev/null | head -1)
if [[ -n "$TRUST_PLUGIN" ]]; then
    source "$TRUST_PLUGIN"
    PROJECT=$(_trust_project_name)
    TRUST_SCORES=$(_trust_scores_batch "$PROJECT")
fi
```

Multiply each agent's raw triage score by its trust score. No trust data → use 1.0. Safety floors: fd-safety and fd-correctness never below sonnet regardless of trust score.

---

## Step 2.2a: Research Context Dispatch [review only, between stages]

**Activates when:** Stage 1 findings reference uncertain external patterns.

**Trigger conditions** (any):
- Finding questions whether a pattern is current best practice
- Finding flags a pattern as "possibly deprecated"
- Finding is uncertain about framework's recommended approach
- Finding notes "looks like [known pattern] but I'm not sure"

**If triggered**: Select 1-2 research agents, construct focused query, dispatch (NOT background — wait, max 60s). Inject result into Stage 2 prompts as `## Research Context (from Stage 1.5)`.

**Budget**: Max 2 dispatches. **Skip if**: All P2/improvements, no Stage 2 planned, no external references.

---

## Step 1.0.6: Model Discovery (interrank)

**Activates when:** interrank MCP server is available AND `budget.yaml → model_discovery.enabled` is true.

Run model discovery to refresh the candidate pool for multi-provider dispatch:

```bash
queries=$(bash ${CLAUDE_PLUGIN_ROOT}/scripts/discover-models.sh 2>/dev/null)
```

If the script outputs query lines (JSON objects), execute each via the corresponding MCP tool:
1. `recommend_model` queries — one per agent tier (checker, analytical, judgment)
2. `cost_leaderboard` queries — Pareto frontier for coding and agentic domains

For each result, merge new candidates into `config/flux-drive/model-registry.yaml`:
- Skip models already in registry (match by `model_id`)
- Add new models with `status: candidate`, `discovered: {today}`, interrank score/confidence
- Set `eligible_tiers` from the query's tier parameter

**Frequency**: Controlled by `model_discovery.refresh_interval` (default: weekly). The script checks `last_discovery` timestamp and exits early if within interval. Use `--force` to override.

**Fallback**: Skip silently if interrank MCP unavailable, script fails, or no queries generated. Never a gate.
