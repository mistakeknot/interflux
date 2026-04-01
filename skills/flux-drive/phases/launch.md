# Phase 2: Launch (Task Dispatch)

This phase respects the `MODE` parameter set in Phase 1. Steps marked **[review only]** are skipped in research mode. Steps marked **[research only]** are skipped in review mode. Unmarked steps apply to both modes.

### Step 2.0: Prepare output directory

Create the output directory before launching agents. Resolve to an absolute path:
```bash
mkdir -p {OUTPUT_DIR}  # Must be absolute, e.g. /root/projects/Foo/docs/research/flux-drive/my-doc-name
```

Then enforce run isolation before dispatch:
```bash
find {OUTPUT_DIR} -maxdepth 1 -type f \( -name "*.md" -o -name "*.md.partial" -o -name "peer-findings.jsonl" \) -delete
```

Use a timestamped `OUTPUT_DIR` only when you intentionally need to preserve previous run artifacts.

### Step 2.0.4: Composer dispatch plan (optional)

If the Composer is available (`_COMPOSE_LIB_SOURCED=1`), query `compose_dispatch` for a pre-computed agent plan. If it returns agents (`compose_has_agents`), the plan is **authoritative** — skip Steps 2.0.5–2.1e, write document to temp files (Step 2.1c), dispatch agents from the plan with their assigned models, and skip to Step 2.3. If Composer is unavailable or returns no agents, fall through to Steps 2.0.5–2.2.

### Step 2.0.5: Resolve agent models

**Skip if `COMPOSER_ACTIVE=1`** — Composer plan includes model assignments.

Source Clavain's `lib-routing.sh` (find in `~/.claude/plugins/cache/*/clavain/*/scripts/`). Measure complexity signals: `REVIEW_TOKENS` (file chars / 4), `REVIEW_FILE_COUNT` (git diff --name-only), `REVIEW_DEPTH=1`. Call `routing_resolve_agents --phase "$PHASE" --agents "agent1,agent2" --prompt-tokens --file-count --reasoning-depth` → returns JSON model map. Pass `model:` to each Agent tool call. Fallback: if lib-routing.sh unavailable, agents use frontmatter defaults. Progressive enhancement, never a gate.

### Step 2.1: Retrieve knowledge context

Before launching agents, retrieve relevant knowledge entries for each selected agent. This step is OPTIONAL — if qmd (via interknow plugin) is unavailable, skip and proceed to Step 2.2.

**For each selected agent**, construct a retrieval query:
1. Combine the agent's domain keywords with the document summary from Phase 1
2. Use the qmd MCP tool (provided by interknow) to search:
   ```
   Tool: mcp__plugin_interknow_qmd__vsearch
   Parameters:
     collection: "interknow"
     query: "{agent domain} {document summary keywords}"
     path: "config/knowledge/"
     limit: 5
   ```
3. If qmd returns results, format them as a knowledge context block

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

**Cap**: 5 entries per agent maximum. If qmd returns more, take the top 5 by relevance score.

**Fallback**: If qmd MCP tool is unavailable or errors, skip knowledge injection entirely — agents run without it (effectively v1 behavior). Do NOT block agent launch on qmd failures.

**Pipelining**: Start qmd queries before agent dispatch. While queries run, prepare agent prompts. Inject results when both are ready.

### Step 2.1-research: Build research prompts and dispatch [research only]

**Skip this entire section in review mode.** In research mode, build per-agent research prompts with the query profile (type, keywords, scope, depth), project context, and domain research directives (if detected). Output format: Sources → Findings → Confidence → Gaps. Write to `{OUTPUT_DIR}/{agent-name}.md.partial`, rename to `.md` with `<!-- flux-research:complete -->` sentinel when done.

Dispatch all agents via Task tool with `run_in_background: true`. Project Agents use `subagent_type: general-purpose`. Timeouts: quick=30s, standard=2min, deep=5min. Then skip to Step 2.3.

---

### Step 2.1a: Load domain-specific review criteria [review only]

**Skip this step if Step 1.0.1 detected no domains** (document profile shows "none detected"). **Skip this step in research mode** (research agents receive domain directives via the research prompt template above).

For each detected domain (from the Document Profile's `Project domains` field), load the corresponding domain profile and extract per-agent injection criteria:

1. **Read the domain profile file**: `${CLAUDE_PLUGIN_ROOT}/config/flux-drive/domains/{domain-name}.md`
2. **For each selected agent**, find the `### fd-{agent-name}` subsection under `## Injection Criteria`
3. **Extract the bullet points** — these are the domain-specific review criteria for that agent
4. **Store as `{DOMAIN_CONTEXT}`** per agent, formatted as shown in the prompt template below

**Multi-domain injection:**
- Inject criteria from ALL detected domains, not just the primary one (a game server should get both `game-simulation` and `web-api` criteria)
- Order sections by confidence score (primary domain first)
- **Cap at 3 domains** to prevent prompt bloat — if more than 3 detected, use only the top 3 by confidence
- If a domain profile has no matching `### fd-{agent-name}` section for a particular agent, skip that domain for that agent

**Fallback**: If the domain profile file doesn't exist or can't be read, skip that domain silently. Do NOT block agent launch on domain profile failures.

**Performance**: Domain profile files are small (~90-100 lines each). Reading 1-3 files adds negligible overhead. This step should take <1 second.

### Step 2.1d: Load active overlays (interspect Type 1) [review only]

For each selected agent, load pre-computed overlay content using the shared library functions from `lib-interspect.sh`. **Do NOT inline YAML parsing** — use the canonical functions to avoid divergence (finding A2).

1. Source `lib-interspect.sh` and call `_interspect_read_overlays "{agent-name}"`
2. The function handles: directory existence check, file scanning, YAML frontmatter parsing via `_interspect_overlay_is_active`, body extraction via `_interspect_overlay_body`, and concatenation
3. If the function returns non-empty content, store it as `{OVERLAY_CONTEXT}` for that agent
4. **Re-sanitize** the returned content before injection (defense-in-depth against hand-edited overlays): call `_interspect_sanitize "$content" 2000`. If sanitization fails (returns non-zero), skip the overlay and log a warning.

**Budget check:** Call `_interspect_count_overlay_tokens "$content"` (canonical: `wc -w * 1.3`). If total exceeds 500 tokens, log `"WARNING: Overlay budget exceeded for {agent}. Using first N of M overlays."` and truncate to the overlays that fit.

**Fallback:** If the overlays directory doesn't exist or contains no active overlays for an agent, skip silently. The Overlay Context section is omitted from that agent's prompt.

**Performance:** Overlay files are tiny (~100 words each, max 500 tokens total per agent). Reading 1-5 files per agent adds negligible overhead.

### Step 2.1c: Write document to temp file(s) [review only]

Write the document (or per-agent slices) to temp files so agents can Read them instead of receiving inline content. This eliminates document duplication across agent prompts.

**Timestamp**: Generate once for all temp files in this run:
```bash
TS=$(date +%s)
```

#### Case 1: File/directory inputs — small document (< 200 lines)

One shared file for all agents:
```bash
REVIEW_FILE="/tmp/flux-drive-${INPUT_STEM}-${TS}.md"
```
Write the full document content. All agents reference this single file.

#### Case 2: File/directory inputs — document slicing active (>= 200 lines)

1. **Classify sections:** Invoke interserve MCP `classify_sections` tool with `file_path` set to the document path.
2. **Check result:** If `status` is `"no_classification"`, fall back to Case 1 (all agents get the original file via shared path).
3. **Generate per-agent files:** For each agent in `slicing_map`:
   - If agent is cross-cutting (fd-architecture, fd-quality): use the shared `REVIEW_FILE` from Case 1.
   - If agent has zero priority sections: skip dispatching this agent entirely.
   - Otherwise: write the per-agent temp file following `phases/slicing.md` → Per-Agent Temp File Construction. File pattern: `/tmp/flux-drive-${INPUT_STEM}-${TS}-${agent}.md`
4. **Record all paths:** Store `REVIEW_FILE_${agent}` paths for prompt construction in Step 2.2.

See `phases/slicing.md` → Document Slicing for the complete classification algorithm, per-agent file structure, and pyramid summary rules.

#### Case 3: Diff inputs — no slicing (< 1000 lines or cross-cutting)

One shared file:
```bash
REVIEW_FILE="/tmp/flux-drive-${INPUT_STEM}-${TS}.diff"
```

#### Case 4: Diff inputs — with per-agent slicing (>= 1000 lines)

See `phases/slicing.md` → Diff Slicing → Per-Agent Temp File Construction for file naming and structure.

Record all REVIEW_FILE paths for use in prompt construction (Step 2.2).

**Peer findings template variables** (used in the Peer Findings Protocol section of the prompt template):
```
FINDINGS_HELPER = ${CLAUDE_PLUGIN_ROOT}/scripts/findings-helper.sh
AGENT_NAME = <the agent's short name, e.g., fd-safety>
```

The orchestrator performs string substitution when building the Task prompt — replacing `{FINDINGS_HELPER}` with the absolute path and `{AGENT_NAME}` with the agent's short name. Same pattern as `{OUTPUT_DIR}` and `{REVIEW_FILE}`.

### Step 2.1e: Apply trust multiplier (intertrust feedback) [review only]

Before ranking agents for dispatch, load trust scores and apply as a multiplier on each agent's triage score. See scoring spec: [Trust Multiplier](../../docs/spec/core/scoring.md#trust-multiplier-005-10).

```bash
# Try intertrust first (extracted plugin), fall back to legacy interspect location
TRUST_PLUGIN=$(find ~/.claude/plugins/cache -path "*/intertrust/*/hooks/lib-trust.sh" 2>/dev/null | head -1)
[[ -z "$TRUST_PLUGIN" ]] && TRUST_PLUGIN=$(find ~/.claude/plugins/cache -path "*/interspect/*/hooks/lib-trust.sh" 2>/dev/null | head -1)
if [[ -n "$TRUST_PLUGIN" ]]; then
    source "$TRUST_PLUGIN"
    PROJECT=$(_trust_project_name)
    TRUST_SCORES=$(_trust_scores_batch "$PROJECT")
fi
```

For each candidate agent, look up its trust score from `TRUST_SCORES` (tab-separated `agent\tscore` lines). Multiply the agent's raw triage score by its trust score. If no trust data: use 1.0 (no change).

**Debug output** (when `FLUX_DEBUG=1`):
```
Trust: fd-safety=0.85, fd-correctness=0.92, fd-game-design=0.15, fd-quality=0.78
```

**Fallback:** If lib-trust.sh not found or `_trust_scores_batch` fails, skip entirely (all multipliers = 1.0). Trust is progressive enhancement, never a gate.

### Step 2.2: Stage 1 — Launch top agents [review only]

**Skip this step if `COMPOSER_ACTIVE=1`** — agents were already dispatched in Step 2.0.4.

**Skip this step in research mode** — research mode dispatches all agents in Step 2.1-research above.

**Condition**: Use this step when `DISPATCH_MODE = task` (default).

Launch Stage 1 agents (top 2-3 by triage score, after trust multiplier) as parallel Task calls with `run_in_background: true`.

Wait for Stage 1 agents to complete (use the monitoring from Step 2.3).

### Step 2.2a: Research context dispatch (optional, between stages) [review only]

**Skip this step in research mode** — research agents ARE the context providers; dispatching them to research themselves is circular.

After Stage 1 agents complete but BEFORE the expansion decision (Step 2.2b), check if any Stage 1 findings would benefit from research context.

**Trigger conditions** (any of these):
- A finding references a library/framework version and questions whether the pattern is current best practice
- A finding flags a pattern as "possibly deprecated" or "may have changed"
- A finding identifies a concurrency or data pattern but is uncertain about the framework's recommended approach
- A finding notes "this looks like [known pattern] but I'm not sure" — external confirmation needed

**If triggered:**
1. Select 1-2 research agents based on the finding type:
   - Best practice uncertainty → `interflux:research:best-practices-researcher`
   - Framework/version question → `interflux:research:framework-docs-researcher`
   - Historical context needed → `interflux:research:git-history-analyzer`
2. Construct a focused research query from the specific finding
3. Dispatch via Task tool (NOT run_in_background — wait for result, max 60s)
4. Inject the research result into Stage 2 agent prompts as additional context:
   ```
   ## Research Context (from Stage 1.5)
   Finding [ID] from [agent] prompted research on [topic]:
   [Research result summary — 3-5 lines]
   Source: [agent name], confidence: [high/medium/low]
   ```

**Budget:** Maximum 2 research dispatches between stages. If more findings need research, pick the 2 with highest severity.

**Skip conditions:**
- All Stage 1 findings are P2/improvements (no uncertainty worth resolving)
- User selected "Stop here" (no Stage 2 planned)
- No Stage 1 findings reference external patterns or frameworks

### Steps 2.2a.5–2.2c: Expansion (AgentDropout + Staged Expansion + Stage 2) [review only]

**If Stage 2 candidates exist after Stage 1 completes**, read `phases/expansion.md` for the full expansion protocol: AgentDropout redundancy filter, incremental expansion, domain-aware expansion decision, and Stage 2 dispatch.

**If no Stage 2 candidates exist** (all agents were Stage 1, or Stage 1 was the only stage needed), skip directly to Step 2.3.

### How to launch each agent type (applies to ALL modes — review Stage 1/2 AND research dispatch):

**Project Agents (.claude/agents/)**:
- `subagent_type: general-purpose`
- Include the agent file's full content as the system prompt
- Set `run_in_background: true`

**Plugin Agents (interflux)**:
- Use the native `subagent_type` from the roster (e.g., `interflux:review:fd-architecture`)
- Set `run_in_background: true`

**Cross-AI (Oracle)**:
- Run via Bash tool with `run_in_background: true` and `timeout: 600000`
- Requires `DISPLAY=:99` and `CHROME_PATH=/usr/local/bin/google-chrome-wrapper`
- Output goes to `{OUTPUT_DIR}/oracle-council.md.partial`, renamed to `.md` on success

**Document content**: Write the document to a temp file once; agents Read it as their first action. See Step 2.1c below.

**Exception for very large file/directory inputs** (1000+ lines): Include only the sections relevant to the agent's focus area plus Summary, Goals, and Non-Goals. Note which sections were omitted in the agent's prompt.

**Prompt trimming**: See `phases/shared-contracts.md` for trimming rules.

**Token counting**: After each Agent tool call returns, note the agent's internal ID from the response. Maintain a mapping of `agent_name → agent_id` for all dispatched agents. Pass this mapping to Phase 3 synthesis for actual token counting (see Token Counting Contract in `shared-contracts.md`).

### Step 2.1b: Prepare sliced content for agent prompts [review only]

**Skip this step in research mode** (research agents don't review documents). **Skip this step if no slicing is active** (diff < 1000 lines, or document < 200 lines — all agents receive full content).

Read `phases/slicing.md` now. It contains the complete slicing algorithm for both diff and document inputs, including:
- Routing patterns (which file/section patterns map to which agents)
- Classification of files/sections as priority vs context per agent
- Per-agent content construction (priority in full + context summaries)
- Edge cases and thresholds (80% overlap, safety override)

Apply the appropriate algorithm (Diff Slicing or Document Slicing) based on `INPUT_TYPE`.

### Prompt template for each agent:

Read `references/prompt-template.md` for the full agent prompt template. Key sections to construct per agent:

1. **Output Format**: Write to `{OUTPUT_DIR}/{agent-name}.md.partial` → rename to `.md` with `<!-- flux-drive:complete -->` sentinel. Structure: Findings Index → Verdict → Summary → Issues Found → Improvements.
2. **Review Task**: `You are reviewing a {document_type} for {review_goal}.`
3. **Knowledge Context** (if Step 2.1 returned entries): Include entries with provenance note (independently confirmed vs primed confirmation).
4. **Domain Context** (if Step 2.1a loaded criteria): Domain classification + per-domain bullet points for this agent, up to 3 domains.
5. **Overlay Context** (if Step 2.1d loaded overlays): Review adjustments from previous sessions.
6. **Project Context**: PROJECT_ROOT, INPUT_FILE, divergence warning if detected.
7. **Document/Diff to Review**: File path to `{REVIEW_FILE}` (or per-agent sliced variant). Agent must Read this first.
8. **Focus Area**: Selection reason, relevant sections, depth needed.
9. **Research Escalation**: Max 1 research agent spawn per review if external context would change severity.
10. **Peer Findings Protocol** (review only): Read/write `{OUTPUT_DIR}/peer-findings.jsonl` via `{FINDINGS_HELPER}` — share only blocking/notable findings.

Omit empty sections (no knowledge → no Knowledge Context header, no domains → no Domain Context, etc.).

After each stage launch, tell the user:
- How many agents were launched in that stage
- That they are running in background
- Estimated wait time (~3-5 minutes)

### Step 2.3: Monitor and verify agent completion

Monitor via `bash ${CLAUDE_PLUGIN_ROOT}/scripts/flux-watch.sh {OUTPUT_DIR} {N} {TIMEOUT}` (N=agent count, TIMEOUT=300 for Task/600 for Codex). Falls back to 5s polling if inotifywait unavailable. Research mode: use `<!-- flux-research:complete -->` sentinel and depth-based timeouts (quick=30s, standard=2min, deep=5min).

**Completion verification:** List `{OUTPUT_DIR}/` — expect `.md` per agent. For `.md.partial` only (incomplete): retry once with `run_in_background: false`, timeout 300000ms. Pre-retry guard: skip if `.md` exists. If retry fails, write error stub per `phases/shared-contracts.md`. Clean up `.md.partial` files. Report: "N/M completed, K retried, J failed".
