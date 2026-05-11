# Agent Prompt Template

This is the full template for constructing per-agent review prompts. The orchestrator reads this when building prompts for dispatched agents.

<!-- This template implements the Findings Index contract from shared-contracts.md -->

```
## Output Format

Write findings to `{OUTPUT_DIR}/{agent-name}.md.partial`. Rename to `.md` when done.
Add `<!-- flux-drive:complete -->` as the last line before renaming.

ALL findings go in that file — do NOT return findings in your response text.

File structure (the run-uuid line MUST be the first non-empty line):

<!-- run-uuid: {RUN_UUID} -->

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

The run-uuid is the orchestrator's quire-mark — synthesis rejects findings
whose run-uuid does not match the current run (this prevents stale outputs
from prior runs and foreign-agent files in the OUTPUT_DIR from contaminating
synthesis). Copy `{RUN_UUID}` exactly as provided.

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
