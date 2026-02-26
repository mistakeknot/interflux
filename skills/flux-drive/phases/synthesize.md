# Phase 3: Synthesize

This phase respects the `MODE` parameter set in Phase 1. Steps marked **[review only]** are skipped in research mode. Steps marked **[research only]** are skipped in review mode. Unmarked steps apply to both modes.

### Step 3.0: Verify all agents completed

Phase 2 (Step 2.3) guarantees one `.md` file per launched agent — either findings or an error stub. Verify:

```bash
ls {OUTPUT_DIR}/
```

Confirm N files (one per launched agent). If count < N, Phase 2 did not complete properly — check Step 2.3 output before proceeding.

### Step 3.1: Validate Agent Output

**[research mode]**: Validate that each research agent's output contains `### Sources`, `### Findings`, `### Confidence`, and `### Gaps` sections. Check for `<!-- flux-research:complete -->` sentinel. Classification:
- **Valid**: All sections present with sentinel → proceed
- **Error/Missing**: Agent failed → create error stub (same as review mode)

Report: "{N}/{M} research agents completed successfully"

Then skip to **Step 3.2**.

**[review mode]**: For each agent's output file, validate structure before reading content:

1. Check the file starts with `### Findings Index` (first non-empty line)
2. Verify index lines match `- SEVERITY | ID | "Section" | Title` pattern
3. Check for a `Verdict:` line after the index entries
4. Classification:
   - **Valid**: Findings Index parsed successfully → proceed with index-first collection
   - **Error**: File contains "verdict: error" or "Verdict: error" → note as "agent failed" in summary, don't count toward convergence
   - **Malformed**: File exists but Findings Index is missing/unrecognizable → fall back to prose-based reading (read Summary + Issues sections directly)
   - **Missing**: File doesn't exist or is empty → "no findings"

Report validation results to user: "5/6 agents returned valid Findings Index, 1 failed"

### Step 3.2: Delegate to Synthesis Subagent

**Do NOT read agent output files yourself.** Delegate ALL collection, validation, deduplication, and verdict writing to a synthesis subagent. This keeps agent prose entirely out of the host context.

**[research mode]**: Launch the **intersynth research synthesis agent**:

```
Task(intersynth:synthesize-research):
  prompt: |
    OUTPUT_DIR={OUTPUT_DIR}
    VERDICT_LIB={CLAUDE_PLUGIN_ROOT}/../../os/clavain/hooks/lib-verdict.sh
    RESEARCH_QUESTION={RESEARCH_QUESTION}
    QUERY_TYPE={type}
    ESTIMATED_DEPTH={estimated_depth}
```

The intersynth agent reads all research agent output files, merges findings with source attribution, ranks sources, writes verdicts, and returns a compact answer. It writes `{OUTPUT_DIR}/synthesis.md`.

After the synthesis subagent returns:
1. Its return value is the compact answer (~5-10 lines) — display this immediately as the quick answer
2. Read `{OUTPUT_DIR}/synthesis.md` for the full report to present to the user
3. The host agent never touched any individual agent output file
4. Skip to **Step 3.5-research** (present research output)

**[review mode]**: Launch the **intersynth review synthesis agent**:

```
Task(intersynth:synthesize-review):
  prompt: |
    OUTPUT_DIR={OUTPUT_DIR}
    VERDICT_LIB={CLAUDE_PLUGIN_ROOT}/../../os/clavain/hooks/lib-verdict.sh
    MODE=flux-drive
    CONTEXT="Reviewing {INPUT_TYPE}: {INPUT_STEM} ({N} agents, {early_stop_note})"
    FINDINGS_TIMELINE={OUTPUT_DIR}/peer-findings.jsonl
```

The intersynth agent handles validation, collection, deduplication, verdict writing, and report generation. It writes `{OUTPUT_DIR}/summary.md` and `{OUTPUT_DIR}/findings.json`, then returns a compact ~15-line summary.

After the synthesis subagent returns:
1. Its return value is the compact summary (~10-15 lines) — display this immediately
2. Read `{OUTPUT_DIR}/summary.md` for the full report to present to the user
3. The host agent never touched any individual agent output file

### Step 3.3: (Handled by synthesis subagent)

Deduplication, convergence tracking, conflict detection, and cognitive agent dedup are all performed by the synthesis subagent above. The 5 dedup rules (defined in `docs/spec/core/synthesis.md` Step 3) are executed in the subagent's context:

1. Same file:line + same issue → merge, credit all agents
2. Same file:line + different issues → keep separate, tag co-located
3. Same issue + different locations → keep separate, cross-reference
4. Conflicting severity → use highest
5. Conflicting recommendations → preserve both with attribution

### Step 3.4: Update the Document

**The write-back strategy depends on input type:**

#### For file inputs (plans, brainstorms, specs, etc.)

Write findings to `{OUTPUT_DIR}/summary.md` (same as repo reviews). Do NOT modify `INPUT_FILE` by default.

The summary file should contain:

```markdown
## Flux Drive Enhancement Summary

Reviewed by N agents on YYYY-MM-DD.
[If divergence detected:] **WARNING: This document is outdated.** The codebase has diverged from the described [tech stack]. Consider archiving this document and writing a new one.

### Key Findings
- [Top 3-5 findings across all agents, with convergence: "(N/M agents)"]

### Issues to Address
- [ ] [Issue 1 — from agents X, Y, Z] (severity, N/M agents)
- [ ] [Issue 2 — from agent Y] (severity)
- ...

### Improvements Suggested
- [Numbered, with rationale and agent attribution]

### Individual Agent Reports
- [{agent-name}](./{agent-name}.md) — [1-line verdict summary]
- ...
```

After writing the summary file, ask:

```yaml
AskUserQuestion:
  question: "Summary written to {OUTPUT_DIR}/summary.md. Add inline annotations to the original document?"
  options:
    - label: "No, summary only (Recommended)"
      description: "Keep the original document clean"
    - label: "Yes, add inline annotations"
      description: "Add findings as blockquotes in the original document"
```

If the user opts in to inline annotations, then apply the existing inline logic: add the Enhancement Summary header at the top of `INPUT_FILE` and add per-section blockquotes:

```markdown
> **Flux Drive** ({agent-name}): [Concise finding or suggestion]
```

#### For repo reviews (directory input, no specific file)

Do NOT modify the repo's README or any existing files. Instead, write a new summary file to `{OUTPUT_DIR}/summary.md` that:

- Summarizes all findings organized by topic
- Links to individual agent reports in the same directory
- Includes the same Enhancement Summary format (Key Findings, Issues to Address checklist)

### Step 3.4a: Generate findings.json

After collecting and deduplicating findings, generate `{OUTPUT_DIR}/findings.json`:

```json
{
  "reviewed": "YYYY-MM-DD",
  "input": "{INPUT_PATH}",
  "agents_launched": ["agent1", "agent2"],
  "agents_completed": ["agent1", "agent2"],
  "findings": [
    {
      "id": "P0-1",
      "severity": "P0",
      "agent": "fd-architecture",
      "section": "Section Name",
      "title": "Short description",
      "convergence": 3
    }
  ],
  "improvements": [
    {
      "id": "IMP-1",
      "agent": "fd-quality",
      "section": "Section Name",
      "title": "Short description"
    }
  ],
  "verdict": "needs-changes",
  "early_stop": false
}
```

Use the Write tool to create this file. The orchestrator generates this from the collected Findings Indexes — agents never write JSON.

**Verdict logic**: If any finding is P0 → "risky". If any P1 → "needs-changes". Otherwise → "safe".

### Step 3.4b: Generate cost report

After collecting findings and generating findings.json, compile a cost report comparing estimated vs actual token consumption.

**Step 3.4b.1: Collect actual token data**

For each launched agent, query interstat for actual tokens:
```bash
sqlite3 ~/.claude/interstat/metrics.db "
  SELECT agent_name,
         COALESCE(input_tokens,0) + COALESCE(output_tokens,0) as billing_tokens,
         COALESCE(input_tokens,0) + COALESCE(cache_read_tokens,0) + COALESCE(cache_creation_tokens,0) as effective_context
  FROM agent_runs
  WHERE session_id = '{current_session_id}'
    AND agent_name IN ({launched_agents_quoted})
  ORDER BY agent_name;
"
```

**Fallback:** If interstat has no data yet (tokens not backfilled until SessionEnd), use `result_length` as a proxy and note "Actual tokens pending backfill — showing result length."

**Step 3.4b.2: Compute deltas**

For each agent:
```
delta_pct = ((actual - estimated) / estimated) * 100
```

**Step 3.4b.3: Add to findings.json**

Extend the findings.json schema with a `cost_report` field:
```json
{
  "cost_report": {
    "budget": 150000,
    "budget_type": "plan",
    "estimated_total": 120000,
    "actual_total": 115000,
    "agents": [
      {
        "name": "fd-architecture",
        "estimated": 42000,
        "actual": 38000,
        "delta_pct": -10,
        "source": "interstat",
        "slicing_applied": false
      }
    ],
    "deferred": [
      {
        "name": "fd-safety",
        "estimated": 45000,
        "reason": "budget"
      }
    ],
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
}
```

**Convergence with document slicing:** When document slicing is active (`slicing_map` available from Phase 2), adjust convergence scoring:
- Only count agents that received the relevant section as `priority` when computing convergence counts. An agent that only saw a context summary cannot meaningfully converge on the same finding.
- If 2+ agents agree on a finding AND reviewed different priority sections (per `slicing_map`), boost the convergence score by 1. Cross-section agreement is higher confidence than same-section agreement. Tag with `"slicing_boost": true` in findings.json.
- Track "Request full section" annotations: count total across all agent outputs. Quality target: ≤5% of agent outputs contain section requests after 10 reviews. Include this request verbatim in synthesis output (v1 — do NOT re-dispatch or re-read sections).

### Step 3.5-research: Present Research Output [research only]

Read `{OUTPUT_DIR}/synthesis.md` and present to user. When complete, display:

```
Research complete!

Output: {OUTPUT_DIR}/synthesis.md
Agents: {N} dispatched, {M} completed, {K} failed
Sources: {total} ({internal} internal, {external} external)

Key answer: [1-2 sentence summary]
```

Then skip to **Step 3.7** (cleanup). Steps 3.5, 3.6, and post-synthesis compounding are review-only.

### Step 3.5: Report to User [review mode]

Present the synthesis report using this exact structure. Fill in each section from the collected findings.

```markdown
## Flux Drive Review — {INPUT_STEM}

**Reviewed**: {YYYY-MM-DD} | **Agents**: {N launched}, {M completed} | **Verdict**: {safe|needs-changes|risky}
[If early stop:] *(Stage 1 only — {K} agents skipped as unnecessary)*

### Verdict Summary
| Agent | Status | Summary |
|-------|--------|---------|
[One row per agent from verdict_parse_all() output. CLEAN agents get a 1-line "no issues" summary. NEEDS_ATTENTION agents get a 1-line finding summary.]

### Critical Findings (P0)
[List P0 findings with agent attribution and convergence. If none: "None."]

### Important Findings (P1)
[List P1 findings with convergence counts: "(3/5 agents)". If none: "None."]

### Improvements Suggested
[Top 3-5 improvements, prioritized. Each with agent attribution.]

### Section Heat Map
| Section | Issues | Improvements | Agents Reporting |
|---------|--------|-------------|-----------------|
| [Section Name] | P0: N, P1: N | N | agent1, agent2 |

### Conflicts
[Any disagreements between agents. If none: "No conflicts detected."]

### Cost Report
| Agent | Estimated | Actual | Delta | Source |
|-------|-----------|--------|-------|--------|
| {agent} | {est}K | {actual}K | {delta}% | {interstat|default} |
| **TOTAL** | **{est_total}K** | **{actual_total}K** | **{delta}%** | |

Budget: {budget_type} ({BUDGET_TOTAL/1000}K). Used: {actual_total/1000}K ({pct}%).
[If agents deferred:] Deferred: {N} agents ({deferred_total/1000}K est.) — override available at triage.
[If dropout active:] AgentDropout: {dropped_count} agents pruned, saving ~{dropout_savings/1000}K tokens.
[If actual_total > BUDGET_TOTAL:] Warning: Over budget by {(actual_total - BUDGET_TOTAL)/1000}K.
[If interstat data unavailable:] *Actual tokens pending backfill — showing estimates only.*

### Files
- Summary: `{OUTPUT_DIR}/summary.md`
- Findings: `{OUTPUT_DIR}/findings.json`
- Individual reports: `{OUTPUT_DIR}/{agent-name}.md`

### Slicing Report

[Include this section only when slicing was active (diff >= 1000 lines or document >= 200 lines).]

See `phases/slicing.md` → Slicing Report Template for the full table format and fields.

[If this is the first flux-drive run on this project (interknow config/knowledge/ was empty):]
*First review on this project — building knowledge base for future reviews.*

### Beads Created
[Populated by Step 3.6. If beads not configured: "*Beads not configured — run `bd init` to enable.*"]
```

**After the report**, suggest next steps based on the verdict:
- **risky**: "Consider addressing P0 findings before proceeding. Run `/clavain:resolve` to auto-fix."
- **needs-changes**: "Review P1 findings. Run `/interflux:flux-drive` again after changes to verify."
- **safe**: "No blocking issues found. Individual reports available for detailed review."

### Step 3.6: Create Beads from Findings [review only]

**Skip this step in research mode** — research findings don't create tracked work items.

After presenting the report, create beads issues to track actionable findings. This ensures review work isn't lost.

**Prerequisite check**: Run `test -d {PROJECT_ROOT}/.beads && echo "beads"`. If `.beads/` doesn't exist, skip this step entirely — beads isn't set up for this project.

#### What becomes a bead

| Severity | Action | Priority |
|----------|--------|----------|
| P0 | Always create bead | `--priority=0` |
| P1 | Always create bead | `--priority=1` |
| P2 | Create bead if ≤5 total findings (otherwise skip noise) | `--priority=2` |
| IMP | Do not create beads (improvements are suggestions, not tracked work) | — |

#### Creating beads

For each qualifying finding, run:

```bash
bd create --title="[fd] {finding_title}" --type=task --priority={priority} \
  --description="From flux-drive review of {INPUT_STEM} ({YYYY-MM-DD}).

Agent: {agent_name}
Section: {section}
Severity: {severity}
Convergence: {N}/{M} agents

{1-2 sentence summary of the finding and recommended fix}

Review output: {OUTPUT_DIR}/{agent-name}.md"
```

**Naming convention**: Prefix titles with `[fd]` so beads from flux-drive reviews are easy to filter.

**Deduplication**: Before creating a bead, search for existing open beads with similar titles:
```bash
bd list --status=open 2>/dev/null | grep -i "{key_phrase}"
```
If a matching bead already exists, skip creation and note: "Existing bead {ID} covers this finding."

**Grouping**: If multiple findings are closely related (e.g., same root cause flagged by different agents), create ONE bead that references all findings rather than N separate beads.

#### Report beads in output

After creating beads, append to the Step 3.5 report:

```markdown
### Beads Created
| Bead ID | Priority | Title |
|---------|----------|-------|
| {id} | P{n} | {title} |

{N} beads created from {M} findings. Use `bd list --status=open` to see all.
```

If `.beads/` didn't exist, append instead:
```markdown
### Beads
*Beads not configured for this project. Run `bd init` to enable issue tracking from reviews.*
```

### Step 3.7: Clean up temp files

Remove document temp files created in Phase 2 (Step 2.1c):
```bash
rm -f /tmp/flux-drive-${INPUT_STEM}-*.md /tmp/flux-drive-${INPUT_STEM}-*.diff 2>/dev/null
```

This cleanup runs after synthesis, not before — agents may still be reading temp files during retry (Step 2.3).

---

## Post-Synthesis: Silent Compounding [review only]

**Skip this section in research mode** — research findings don't compound into the knowledge base.

After presenting the review to the user (Step 3.5), run a compounding step in the background. This step is SILENT — no user-visible output. The user's last interaction is the Step 3.5 report.

### Purpose

Extract durable patterns from agent findings and save them as knowledge entries via the interknow plugin. This is how flux-drive "gets smarter" over time. Knowledge entries are stored in interknow's `config/knowledge/` directory (was `interknow config/knowledge/`).

### Implementation

Launch a background Task agent (model: sonnet) with this prompt:

````markdown
You are the flux-drive compounding agent. Your job is to extract durable, reusable patterns from review findings and save them as knowledge entries.

## Input

Read the agent output files in {OUTPUT_DIR}/:
- Read the Findings Index from each agent's .md file (first ~30 lines)
- For P0/P1 findings, read the full prose section for evidence anchors

## Decision Criteria

For each finding, decide: **compound or skip?**

**Compound** (save as knowledge entry) when the finding is:
- A pattern likely to recur in future reviews (not a one-off typo or style nit)
- Backed by concrete evidence (file paths, line numbers, symbol names)
- Generalizable beyond this specific document (not "line 47 has a typo")

**Skip** when:
- The finding is document-specific and won't recur
- The finding lacks evidence anchors
- The finding is a stylistic preference, not a correctness or safety concern
- The finding is an improvement suggestion, not a discovered pattern

## Knowledge Entry Format

For each finding worth compounding, write a markdown file to `interknow config/knowledge/`:

Filename: `{short-kebab-case-description}.md` (e.g., `auth-middleware-swallows-cancellation.md`)

Content:
```yaml
---
lastConfirmed: {today's date YYYY-MM-DD}
provenance: independent
---
{1-3 sentence description of the pattern}

Evidence: {file paths, symbol names, line ranges from the agent's finding}
Verify: {1-3 steps to confirm this finding is still valid}
```

## Provenance Rules

- If this is a NEW finding (no matching knowledge entry was injected): set `provenance: independent`
- If this finding MATCHES a knowledge entry that was injected into the agent's context: check the agent's provenance note
  - If the agent noted "independently confirmed": update the existing entry's `lastConfirmed` date and set `provenance: independent`
  - If the agent noted "primed confirmation": do NOT update `lastConfirmed` — the confirmation is primed, not genuine

## Sanitization Rules

Before writing ANY knowledge entry, sanitize it:
- Remove specific file paths from external repos (not the Clavain repo)
- Remove hostnames, internal endpoints, org names, customer identifiers
- Generalize to heuristic form: "Auth middleware often swallows context cancellation" not "auth.go:47 in ProjectX"
- Entries about Clavain's own codebase CAN include Clavain-specific paths

## Decay Check

After compounding new entries, scan existing entries in `interknow config/knowledge/`:
- Read each entry's `lastConfirmed` date
- If an entry has not been independently confirmed in the last 10 reviews (approximate by date: >60 days), move it to `interknow config/knowledge/archive/`
- Log archived entries (for your own tracking, not user-visible)

## Output

This agent produces no user-visible output. It only writes/updates files in `interknow config/knowledge/`.
If compounding fails for any reason, the review is still complete — this is best-effort infrastructure.
````

### First-Run Bootstrap

On the first flux-drive v2 run on a project, the knowledge directory will be empty. The compounding agent will:
1. Create initial knowledge entries from the first review's findings
2. All entries will have `provenance: independent` (no prior entries to be primed by)

Add a note in the Step 3.5 report template: after the Files section, add:
```markdown
[If this is the first flux-drive run on this project (interknow config/knowledge/ was empty):]
*First review on this project — building knowledge base for future reviews.*
```

### Failure Handling

If the compounding Task fails:
- Do NOT report the failure to the user
- Do NOT retry
- The review is complete regardless of compounding success
- Log the error internally for debugging
