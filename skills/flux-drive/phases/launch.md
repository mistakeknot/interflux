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

**Skip this entire section in review mode.** In research mode, after Step 2.1 (knowledge context), build per-agent research prompts and dispatch all agents in a single stage.

For each selected research agent, construct a prompt:

```
## Research Task

Question: {RESEARCH_QUESTION}

Query profile:
- Type: {type}
- Keywords: {keywords}
- Scope: {scope}
- Depth: {estimated_depth}

## Project Context

Project root: {PROJECT_ROOT}

[If domains detected AND Research Directives exist for this agent:]

## Domain Research Directives

This project is classified as: {domain1} ({confidence1}), {domain2} ({confidence2}), ...

Search directives for your focus area in these project types:

### {domain1-name}
{bullet points from domain profile's ### {agent-name} section under ## Research Directives}

### {domain2-name}
{bullet points from domain profile's ### {agent-name} section under ## Research Directives}

Use these directives to guide your search queries and prioritize relevant sources.

[End domain section]

## Output

Write your findings to `{OUTPUT_DIR}/{agent-name}.md.partial`. Rename to `.md` when done.
Add `<!-- flux-research:complete -->` as the last line before renaming.

Structure your output as:

### Sources
- [numbered list of sources with type: internal/external, authority level]

### Findings
[Your research findings, organized by relevance]

### Confidence
- High confidence: [findings well-supported by multiple sources]
- Medium confidence: [findings from single source or indirect evidence]
- Low confidence: [inferences, gaps in available information]

### Gaps
[What you couldn't find or areas needing deeper investigation]
```

Dispatch all selected agents via Task tool with `run_in_background: true`. Then skip to **Step 2.3** (monitor and verify completion).

**Timeouts by depth** (research mode):
| Depth | Per-agent timeout |
|-------|------------------|
| quick | 30 seconds |
| standard | 2 minutes |
| deep | 5 minutes |

---

### Step 2.1a: Load domain-specific review criteria [review only]

**Skip this step if Step 1.0.1 detected no domains** (document profile shows "none detected"). **Skip this step in research mode** (research agents receive domain directives via the research prompt template above).

For each detected domain (from the Document Profile's `Project domains` field), load the corresponding domain profile and extract per-agent injection criteria:

1. **Read the domain profile file**: Try intersense plugin first (`intersense/config/domains/{domain-name}.md`), fall back to `${CLAUDE_PLUGIN_ROOT}/config/flux-drive/domains/{domain-name}.md`
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

**Skip this step in research mode** — research mode dispatches all agents in Step 2.1-research above.

**Condition**: Use this step when `DISPATCH_MODE = task` (default).

Launch Stage 1 agents (top 2-3 by triage score, after trust multiplier) as parallel Task calls with `run_in_background: true`.

Wait for Stage 1 agents to complete (use the polling from Step 2.3).

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

### Step 2.2a.5: AgentDropout — redundancy filter [review only]

**Skip this step in research mode** — research mode uses single-stage dispatch with no candidate pool to prune.

After Stage 1 completes (and optional research dispatch), apply a lightweight redundancy check to the Stage 2 and expansion pool candidates. This step prunes agents whose domains are already well-covered by Stage 1 findings, saving tokens without losing coverage.

**When to run:** Always run this step before the expansion decision (Step 2.2b). It modifies the candidate pool that expansion scoring operates on.

**Exempt agents:** Never drop agents listed in `budget.yaml → exempt_agents` (currently `fd-safety`, `fd-correctness`). These always survive dropout regardless of redundancy signals.

#### Redundancy scoring algorithm

For each Stage 2 / expansion pool agent, compute a redundancy score (0.0 – 1.0) based on Stage 1 output:

```
redundancy_score = 0.0

# 1. Domain convergence — Stage 1 already covered this agent's domain
stage1_domains = set of domains that produced P0/P1 findings in Stage 1
if agent's primary domain ∈ stage1_domains:
    redundancy_score += 0.4

# 2. Adjacency saturation — all of this agent's neighbors ran in Stage 1
agent_neighbors = adjacency_map[agent]
neighbors_in_stage1 = [n for n in agent_neighbors if n ran in Stage 1]
if len(neighbors_in_stage1) == len(agent_neighbors):
    redundancy_score += 0.3   # all neighbors already covered

# 3. Finding density — Stage 1 produced many findings in adjacent domains
adjacent_finding_count = count of P0+P1 findings from agents adjacent to this agent
if adjacent_finding_count >= 3:
    redundancy_score += 0.2   # adjacent domains are well-explored

# 4. Low trust signal — agent has poor historical precision
trust_score = trust_multiplier for this agent (from Step 2.1e, default 1.0)
if trust_score < 0.5:
    redundancy_score += 0.1   # low-trust agents are weaker candidates
```

#### Dropout decision

```
DROPOUT_THRESHOLD = 0.7  (from budget.yaml → dropout.threshold, default 0.7)

for each candidate in Stage 2 + expansion pool:
    if candidate in exempt_agents:
        continue  # never dropped
    if redundancy_score >= DROPOUT_THRESHOLD:
        mark candidate as DROPPED
```

#### Logging (always)

After computing dropout decisions, log the results prominently so users can see what was removed and why:

```
AgentDropout: Evaluated N candidates
  ✓ fd-performance (redundancy: 0.4) — retained
  ✗ fd-quality (redundancy: 0.7) — DROPPED (domain converged + neighbors saturated)
  🛡 fd-safety (redundancy: 0.8) — EXEMPT (safety-critical)
  ✓ fd-game-design (redundancy: 0.1) — retained
Dropped: 1 agent. Estimated savings: ~40K tokens.
```

**Estimated savings** = sum of `agent_defaults[category]` from `budget.yaml` for each dropped agent (adjusted by `slicing_multiplier` if slicing is active).

#### Token savings tracking

Record dropout decisions in the cost report data for Step 3.4b:

```json
{
  "dropout": {
    "evaluated": 4,
    "dropped": ["fd-quality"],
    "retained": ["fd-performance", "fd-game-design"],
    "exempt": ["fd-safety"],
    "estimated_savings": 40000,
    "scores": {
      "fd-quality": 0.7,
      "fd-performance": 0.4,
      "fd-game-design": 0.1,
      "fd-safety": 0.8
    }
  }
}
```

#### Override

If the user selects "Launch all Stage 2 anyway" in Step 2.2b, dropped agents are restored — dropout is advisory, never a hard gate. Log: `"AgentDropout override: restoring N dropped agents per user request."`

#### Skip conditions

Skip this step entirely when:
- Only 1 Stage 2 candidate exists (nothing to drop)
- Stage 1 produced zero findings (no convergence signal — expansion scoring handles this case)
- `budget.yaml → dropout.enabled` is `false`

### Step 2.2b: Domain-aware expansion decision [review only]

**Skip this step in research mode** — all research agents dispatch in a single stage.

After Stage 1 completes (and AgentDropout filtering), read the Findings Index from each Stage 1 output file. Then use the **expansion scoring algorithm** to recommend which Stage 2 agents (and expansion pool agents not dropped by AgentDropout) to launch.

#### Domain adjacency map

Agents with related domains. A finding in one agent's domain makes adjacent agents more valuable:

```yaml
adjacency:
  fd-architecture: [fd-performance, fd-quality]
  fd-correctness: [fd-safety, fd-performance]
  fd-safety: [fd-correctness, fd-architecture]
  fd-quality: [fd-architecture, fd-user-product]
  fd-user-product: [fd-quality, fd-game-design]
  fd-performance: [fd-architecture, fd-correctness]
  fd-game-design: [fd-user-product, fd-correctness, fd-performance]
```

#### Expansion scoring algorithm

For each Stage 2 / expansion pool agent, compute an expansion score:

```
expansion_score = 0

# Severity signals (from Stage 1 findings)
if any P0 in an adjacent agent's domain:    expansion_score += 3
if any P1 in an adjacent agent's domain:    expansion_score += 2
if Stage 1 agents disagree on a finding in this agent's domain: expansion_score += 2

# Domain signals
if agent has domain injection criteria for a detected domain: expansion_score += 1
```

#### Expansion decision

| max(expansion_scores) | Decision |
|---|---|
| ≥ 3 | **RECOMMEND expansion** — present specific agents with reasoning (default first option) |
| 2 | **OFFER expansion** — present as user's choice (no default recommendation) |
| ≤ 1 | **RECOMMEND stop** — "Stop here" is the default first option |

#### Presenting to user

Use **AskUserQuestion** with reasoning about WHY each agent should be added:

```yaml
AskUserQuestion:
  question: "Stage 1 complete. [findings summary]. [expansion reasoning]"
  options:
    # When recommending expansion (max score ≥ 3):
    - label: "Launch [specific agents] (Recommended)"
      description: "[reasoning — e.g., 'P0 in game design → fd-correctness validates simulation state']"
    - label: "Launch all Stage 2 (N agents)"
      description: "Full coverage from remaining agents"
    - label: "Stop here"
      description: "Stage 1 findings are sufficient"
    # When offering (max score = 2):
    - label: "Launch [specific agents]"
      description: "[reasoning]"
    - label: "Stop here"
      description: "Stage 1 findings are sufficient"
    # When recommending stop (max score ≤ 1):
    - label: "Stop here (Recommended)"
      description: "Only P2/improvements found — Stage 1 is sufficient"
    - label: "Launch all Stage 2 anyway"
      description: "Run remaining N agents for extra coverage"
```

**Example reasoning**: "Stage 1 found a P0 in game design (death spiral in storyteller). fd-correctness is adjacent to fd-game-design and has domain criteria for simulation state consistency — it could validate whether this is a code bug or design issue. Launch fd-correctness + fd-performance for Stage 2?"

If the user chooses expansion, launch only the recommended agents (not all Stage 2) unless they explicitly select "Launch all."

### Step 2.2c: Stage 2 — Remaining agents (if expanded) [review only]

**Skip this step in research mode.**

Launch Stage 2 agents with `run_in_background: true`. Wait for completion using the same polling mechanism.

### How to launch each agent type (applies to Stage 1 and Stage 2):

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

### Step 2.1b: Prepare sliced content for agent prompts [review only]

**Skip this step in research mode** (research agents don't review documents). **Skip this step if no slicing is active** (diff < 1000 lines, or document < 200 lines — all agents receive full content).

Read `phases/slicing.md` now. It contains the complete slicing algorithm for both diff and document inputs, including:
- Routing patterns (which file/section patterns map to which agents)
- Classification of files/sections as priority vs context per agent
- Per-agent content construction (priority in full + context summaries)
- Edge cases and thresholds (80% overlap, safety override)

Apply the appropriate algorithm (Diff Slicing or Document Slicing) based on `INPUT_TYPE`.

### Prompt template for each agent:

<!-- This template implements the Findings Index contract from shared-contracts.md -->

```
## Output Format

Write findings to `{OUTPUT_DIR}/{agent-name}.md.partial`. Rename to `.md` when done.
Add `<!-- flux-drive:complete -->` as the last line before renaming.

ALL findings go in that file — do NOT return findings in your response text.

File structure:

### Findings Index
- SEVERITY | ID | "Section" | Title
Verdict: safe|needs-changes|risky

### Summary
[3-5 lines]

### Issues Found
[ID. SEVERITY: Title — 1-2 sentences with evidence]

### Improvements
[ID. Title — 1 sentence with rationale]

Zero findings: empty index + verdict: safe.

---

## Review Task

You are reviewing a {document_type} for {review_goal}.

[Only include this section if knowledge entries were retrieved in Step 2.1 for this agent.
If no knowledge entries exist, omit the entire Knowledge Context section — do not include it empty.]

## Knowledge Context

The following patterns were discovered in previous reviews. Consider them as context but verify independently — do NOT simply re-confirm without checking.

{For each knowledge entry:}
- **Finding**: {entry body — first 1-3 lines}
  **Evidence**: {evidence anchors from entry body}
  **Last confirmed**: {lastConfirmed from frontmatter}

**Provenance note**: If any knowledge entry above matches a finding you would independently flag, note it as "independently confirmed" in your findings. If you are only re-stating a knowledge entry without independent evidence, note it as "primed confirmation" — this distinction is critical for knowledge decay.

## Domain Context

[If domains were detected in Step 1.0.1 AND Step 2.1a extracted criteria for this agent:]

This project is classified as: {domain1} ({confidence1}), {domain2} ({confidence2}), ...

Additional review criteria for your focus area in these project types:

### {domain1-name}
{bullet points from domain profile's ### fd-{agent-name} section}

### {domain2-name}
{bullet points from domain profile's ### fd-{agent-name} section}

[Repeat for up to 3 detected domains. Omit any domain that has no matching section for this agent.]

Apply these criteria **in addition to** your standard review approach. They highlight common issues specific to this project type. Treat them as additional checks, not replacements for your core analysis.

[If no domains detected OR no criteria found for this agent:]
(Omit this section entirely — do not include an empty Domain Context header.)

## Overlay Context

[Only include this section if overlays were loaded in Step 2.1d for this agent. If no active overlays exist, omit entirely.]

The following review adjustments have been learned from previous sessions. Apply them in addition to your standard review approach.

{overlay_content}

## Project Context

Project root: {PROJECT_ROOT}
Document: {INPUT_FILE or "Repo-level review (no specific document)"}

[If document-codebase divergence was detected in Step 1.0, add:]

CRITICAL CONTEXT: The document describes [document's tech stack] but the actual
codebase uses [actual tech stack]. Key actual files to read:
- [file1] — [what it contains]
- [file2] — [what it contains]
- [file3] — [what it contains]
Review the ACTUAL CODEBASE, not what the document describes. Note divergence
as a finding.

## Document to Review

**File path**: `{REVIEW_FILE}` [or `{REVIEW_FILE_{agent-name}}` if document slicing is active]

Your FIRST action must be to Read this file using the Read tool.

[For full-document agents (cross-cutting, or document < 200 lines):]
It contains the full document under review.

[For sliced agents (document >= 200 lines, domain-specific):]
This file contains priority sections for your review domain in full,
plus one-line summaries of other sections. If you need full content
for a summarized section, note "Request full section: {name}" in your findings.

[For repo reviews: Include README + key structural info from Step 1.0 inline,
then reference the temp file for the full content.]

[When divergence exists, also include specific things for THIS agent to
check in the actual codebase — file paths, line numbers, known issues
you spotted during Step 1.0.]

## Diff to Review

[For INPUT_TYPE = diff only — replace the "Document to Review" section above with this:]

### Diff Stats
- Files changed: {file_count}
- Lines: +{added} -{removed}
- Commit: {commit_message or "N/A"}

**Diff file**: `{REVIEW_FILE}` (or `{REVIEW_FILE_{agent-name}}` if per-agent slicing is active)

Your FIRST action must be to Read this file. It contains the diff content for your review.

[If diff slicing is active for this agent, add:]
This file contains your priority hunks in full + context file summaries.
If you need full hunks for a context file, note it as "Request full hunks: {filename}" in your findings.

[Diff slicing active: {P} priority files ({L1} lines), {C} context files ({L2} lines summarized)]

[For cross-cutting agents or small diffs: all agents share one diff file with the full content.]

## Your Focus Area

You were selected because: [reason from triage table]
Focus on: [specific sections relevant to this agent's domain]
Depth needed: [thin sections need more depth, deep sections need only validation]

Be concrete. Reference specific sections by name. Don't give generic advice.

## Research Escalation (Optional)

If you encounter a pattern, library, or practice during review where external context would strengthen your finding, you can spawn a research agent for a quick lookup:

- `Task(interflux:research:best-practices-researcher)` — industry best practices, community conventions
- `Task(interflux:research:framework-docs-researcher)` — official library/framework documentation
- `Task(interflux:research:learnings-researcher)` — past solutions from this project's docs/solutions/
- `Task(interflux:research:git-history-analyzer)` — why code evolved to its current state
- `Task(interflux:research:repo-research-analyst)` — repository conventions and patterns

**Rules:**
- Only escalate when external context would change your finding's severity or recommendation
- Keep queries targeted and specific (one question, not "tell me everything about X")
- Do NOT escalate for general knowledge you already have — only for project-specific or version-specific facts
- Maximum 1 research escalation per review (budget constraint)
- Include the research result in your finding as "Context: [source] confirms/contradicts..."

## Peer Findings Protocol [review only — omit this section entirely in research mode]

Other reviewer agents are analyzing this artifact in parallel. You can share and receive high-severity findings via a shared findings file.

**Findings file**: `{OUTPUT_DIR}/peer-findings.jsonl`

### Writing findings (during your analysis)

When you discover a finding that other agents should know about, append it to the findings file. Only share findings at these severity levels:

- **blocking** — contradicts or invalidates another agent's likely analysis (e.g., "this API endpoint doesn't exist", "this data model was removed")
- **notable** — significant finding that may affect other agents' conclusions (e.g., "no authentication on admin endpoints", "critical race condition in shared state")

Do NOT share informational or improvement-level findings — those belong only in your report.

To write a finding, use the Bash tool:
```bash
bash {FINDINGS_HELPER} write "{OUTPUT_DIR}/peer-findings.jsonl" "<severity>" "{AGENT_NAME}" "<category>" "<summary>" "<file_ref1>" "<file_ref2>"
```

Where:
- `<severity>` is `blocking` or `notable`
- `<category>` is a short kebab-case tag (e.g., `api-conflict`, `auth-bypass`, `race-condition`)
- `<summary>` is a 1-2 sentence description
- `<file_ref>` entries are optional `file:line` references

### Reading peer findings (before your final report)

**Before writing your final report**, check for peer findings:

```bash
bash {FINDINGS_HELPER} read "{OUTPUT_DIR}/peer-findings.jsonl"
```

For each finding returned:
- **blocking**: You MUST acknowledge it in your report. If it affects your domain, adjust your analysis accordingly.
- **notable**: Consider whether it changes any of your recommendations. Note it if relevant.

If the findings file doesn't exist or is empty, proceed normally — you may be the first agent to finish.
```

After each stage launch, tell the user:
- How many agents were launched in that stage
- That they are running in background
- Estimated wait time (~3-5 minutes)

### Step 2.3: Monitor and verify agent completion

This step applies to both review and research modes.

**[research mode]**: Use the completion sentinel `<!-- flux-research:complete -->` instead of `<!-- flux-drive:complete -->`. Use depth-based timeouts (quick=30s, standard=2min, deep=5min) instead of the fixed 5-minute timeout.

After dispatching a stage of agents, report the initial status and then poll for completion:

**Initial status:**
```
Agent dispatch complete. Monitoring N agents...
⏳ fd-architecture
⏳ fd-safety
⏳ fd-quality
...
```

**Polling loop** (every 30 seconds, up to 5 minutes):
1. Check `{OUTPUT_DIR}/` for `.md` files (not `.md.partial` — those are still in progress)
2. For each new `.md` file found since the last check, report:
   ```
   ✅ fd-architecture (47s)
   [2/5 agents complete]
   ```
3. If all expected `.md` files exist, stop polling — all agents are done
4. After 5 minutes, report any agents still pending:
   ```
   ⚠️ Timeout: fd-safety still running after 300s
   ```

**Completion verification** (after polling ends):
1. List `{OUTPUT_DIR}/` — expect one `.md` file per launched agent (not `.md.partial`)
2. For any agent where only `.md.partial` exists (started but did not complete) or no file exists:
   a. Check the background task output for errors
   b. **Pre-retry guard**: If `{OUTPUT_DIR}/{agent-name}.md` already exists (not `.partial`), do NOT retry — the agent completed successfully
   c. **Retry once** (Task-dispatched agents only): Re-launch with the same prompt, `run_in_background: false`, `timeout: 300000` (5 min cap). Do NOT retry Oracle.
   d. If retry produces output, ensure it ends with `<!-- flux-drive:complete -->` and is saved as `{OUTPUT_DIR}/{agent-name}.md` (not `.partial`)
   e. If retry also fails, create an error stub following the format in `phases/shared-contracts.md`.
3. Clean up: remove any remaining `.md.partial` files in `{OUTPUT_DIR}/`
4. Report to user: "N/M agents completed successfully, K retried, J failed"
