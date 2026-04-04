# Phase 2: Launch (Task Dispatch)

This phase respects the `MODE` parameter set in Phase 1. Steps marked **[review only]** are skipped in research mode. Steps marked **[research only]** are skipped in review mode. Unmarked steps apply to both modes.

### Step 2.0: Prepare output directory

Create the output directory before launching agents. Resolve to an absolute path:
```bash
mkdir -p {OUTPUT_DIR}  # Must be absolute, e.g. /root/projects/Foo/docs/research/flux-drive/my-doc-name-20260404T1930
```

OUTPUT_DIR is timestamped by default (see SKILL.md § Run isolation) to prevent cross-run contamination. If the caller passed `--output-dir` explicitly (reusing a fixed path), enforce run isolation by cleaning stale files:
```bash
find {OUTPUT_DIR} -maxdepth 1 -type f \( -name "*.md" -o -name "*.md.partial" -o -name "peer-findings.jsonl" \) -delete
```

### Step 2.0.4: Composer dispatch plan (optional)

If the Composer is available (`_COMPOSE_LIB_SOURCED=1`), query `compose_dispatch` for a pre-computed agent plan. If it returns agents (`compose_has_agents`), the plan is **authoritative** — skip Steps 2.0.5–2.1e, write document to temp files (Step 2.1c), dispatch agents from the plan with their assigned models, and skip to Step 2.3. If Composer is unavailable or returns no agents, fall through to Steps 2.0.5–2.2.

### Step 2.0.5: Resolve agent models

**Skip if `COMPOSER_ACTIVE=1`** — Composer plan includes model assignments.

Source Clavain's `lib-routing.sh` (find in `~/.claude/plugins/cache/*/clavain/*/scripts/`). Measure complexity signals: `REVIEW_TOKENS` (file chars / 4), `REVIEW_FILE_COUNT` (git diff --name-only), `REVIEW_DEPTH=1`. Call `routing_resolve_agents --phase "$PHASE" --agents "agent1,agent2" --prompt-tokens --file-count --reasoning-depth` → returns JSON model map. Pass `model:` to each Agent tool call. Fallback: if lib-routing.sh unavailable, agents use frontmatter defaults. Progressive enhancement, never a gate.

### Step 2.1: Retrieve knowledge context

OPTIONAL — read `references/progressive-enhancements.md` § Step 2.1 for the qmd retrieval protocol and domain keyword table. Skip if qmd unavailable.

### Step 2.1-research: Build research prompts and dispatch [research only]

**Skip this entire section in review mode.** In research mode, build per-agent research prompts with the query profile (type, keywords, scope, depth), project context, and domain research directives (if detected). Output format: Sources → Findings → Confidence → Gaps. Write to `{OUTPUT_DIR}/{agent-name}.md.partial`, rename to `.md` with `<!-- flux-research:complete -->` sentinel when done.

Dispatch all agents via Task tool with `run_in_background: true`. Project Agents use `subagent_type: general-purpose`. Timeouts: quick=30s, standard=2min, deep=5min. Then skip to Step 2.3.

---

### Step 2.1a: Load domain-specific review criteria [review only]

**Skip if** no domains detected or research mode. Read `references/progressive-enhancements.md` § Step 2.1a for the domain profile loading protocol. Store results as `{DOMAIN_CONTEXT}` per agent.

### Step 2.1d: Load active overlays (interspect Type 1) [review only]

OPTIONAL — read `references/progressive-enhancements.md` § Step 2.1d for the overlay loading protocol. Use canonical `lib-interspect.sh` functions (do NOT inline YAML parsing). Store results as `{OVERLAY_CONTEXT}` per agent. Skip silently if overlays directory doesn't exist.

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

OPTIONAL — read `references/progressive-enhancements.md` § Step 2.1e for the trust score loading and multiplication protocol. Multiply each agent's raw triage score by its trust score (1.0 if unavailable). Safety floors: fd-safety and fd-correctness never below sonnet.

### Step 2.2: Stage 1 — Launch top agents [review only]

**Skip this step if `COMPOSER_ACTIVE=1`** — agents were already dispatched in Step 2.0.4.

**Skip this step in research mode** — research mode dispatches all agents in Step 2.1-research above.

**Condition**: Use this step when `DISPATCH_MODE = task` (default).

Launch Stage 1 agents (top 2-3 by triage score, after trust multiplier) as parallel Task calls with `run_in_background: true`.

Wait for Stage 1 agents to complete (use the monitoring from Step 2.3).

### Step 2.2a: Research context dispatch (optional, between stages) [review only]

OPTIONAL — read `references/progressive-enhancements.md` § Step 2.2a for trigger conditions, agent selection, and injection format. Max 2 dispatches between stages. Skip in research mode and when all findings are P2/improvements.

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
