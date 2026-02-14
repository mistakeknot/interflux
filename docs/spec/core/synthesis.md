# Findings Synthesis

> flux-drive-spec 1.0 | Conformance: Core

## Overview

The synthesis phase validates agent outputs, deduplicates findings across agents, tracks convergence, computes a deterministic verdict, and generates both structured (findings.json) and human-readable (summary.md) reports. Index-first collection optimizes performance by parsing structured Findings Indexes before reading prose bodies.

## Specification

### Step 1: Output Validation

Before processing any agent output, validate each file:

1. Check file starts with `### Findings Index` (first non-empty line after metadata)
2. Verify index entries match pattern: `- SEVERITY | ID | "Section" | Title`
3. Check for `Verdict:` line after index entries
4. Classify output state:

| State | Condition | Action |
|-------|-----------|--------|
| **Valid** | Findings Index parsed successfully | Proceed to collection |
| **Error** | Contains "Verdict: error" | Exclude from convergence calculation |
| **Malformed** | File exists but index unrecognizable | Use prose fallback (extract from Summary/Issues) |
| **Missing** | File doesn't exist or empty | Treat as "no findings" |

Report validation results: "5/6 agents returned valid Findings Index, 1 failed"

> **Why this works:** Early validation prevents cascading failures. An agent that crashed mid-execution should not poison the synthesis process or distort convergence statistics.

### Step 2: Findings Collection

Use a two-tier collection strategy:

**Tier 1 — Structured Index (default):**
- Read Findings Index from each valid agent output (~30 lines)
- Parse each entry into: `{severity, id, section, title, agent}`
- Build findings map keyed by `section + title_normalized`

**Tier 2 — Prose Fallback (on-demand):**
Read full prose body only when:
- An issue needs more context (user requests details)
- Agents conflict on the same issue
- Output was classified as Malformed (no valid index)

For malformed outputs, extract findings from:
- Summary section: "Key Findings" bullet list
- Issues section: headings as titles, first paragraph as description

> **Why this works:** The Findings Index contains all metadata needed for deduplication, convergence tracking, and verdict computation. Reading hundreds of lines of prose per agent is unnecessary overhead. Prose is loaded lazily when the orchestrator needs deeper context.

**Reference:** `contracts/findings-index.md` for index format specification.

### Step 3: Deduplication

When multiple agents report the same issue:

1. **Match duplicates** by comparing:
   - Exact section match: `issue1.section === issue2.section`
   - Fuzzy title match: Levenshtein distance < 0.3, or shared keywords (3+ words in common)

2. **Keep the most specific version:**
   - Prefer Project Agent > Plugin Agent (deeper project context)
   - Prefer longer description over shorter (more detail)
   - Preserve all agent attributions in merged metadata

3. **Merge metadata:**
   ```json
   {
     "id": "P1-1",
     "severity": "P1",
     "agents": ["fd-architecture", "fd-safety"],
     "section": "Authentication",
     "title": "Session tokens stored in localStorage",
     "convergence": 2,
     "descriptions": {
       "fd-architecture": "...",
       "fd-safety": "..."
     }
   }
   ```

4. **Flag conflicts:**
   If agents disagree on severity for the same issue:
   - Record both positions: `"severity_conflict": {"fd-architecture": "P1", "fd-quality": "P2"}`
   - Use most severe rating for verdict computation
   - Note conflict in summary report

> **Why this works:** Deduplication prevents double-counting the same issue. Preserving all attributions maintains traceability — the user can see which agents independently found the problem.

### Step 4: Convergence Tracking

For each deduplicated finding, count how many agents independently reported it.

**Convergence metric:** `N/M agents` where:
- N = number of agents that reported this finding
- M = number of agents that completed successfully (excludes Error state)

**Confidence levels:**

| Convergence | Confidence | Interpretation |
|-------------|------------|----------------|
| 3+ agents | High | This is a real issue — multiple perspectives agree |
| 2 agents | Medium | Likely real, worth addressing |
| 1 agent | Low | May be false positive or domain-specific concern |

**Adjustment for Early Stop:**

If the orchestrator stopped after Stage 1 (shallow analysis sufficient):
- M reflects only Stage 1 agents: `M = agents_launched_stage1`
- Report: "Early stop after Stage 1: 4 agents ran, 4 agents skipped as unnecessary"
- Don't penalize convergence: 3/4 with early stop is as valid as 3/8 with full pipeline

**Adjustment for Content Routing (Slicing):**

When agents received different content slices:
- Adjust M per-finding to only count agents that saw relevant content
- Example: Architecture agent got full diff, Safety agent got only auth files
  - For a performance finding in rendering code: M excludes Safety agent (didn't receive that content)
  - For an auth finding: M includes both agents (both saw auth code)
- Tag out-of-scope findings: If an agent flags something in context content (not priority slice), tag as "out-of-scope observation" with lower confidence

> **Why this works:** Naive convergence counting breaks under content routing. An agent that didn't receive the relevant files cannot be counted as "didn't find the issue" — it never had the opportunity. Adjusting M per-finding makes convergence statistics honest and meaningful.

**Implementation notes:**
- Track content routing decisions in orchestrator metadata: `{agent: string, files_received: string[]}`
- When computing convergence for a finding in `file.ts:42`, check which agents received `file.ts`
- Adjust M dynamically: `M = agents_completed.filter(a => a.files_received.includes(finding.file)).length`

### Step 5: Verdict Computation

Compute a deterministic verdict from the highest severity finding:

| Condition | Verdict | Interpretation |
|-----------|---------|----------------|
| Any P0 finding | `risky` | Critical issues present — high risk of breakage/security flaws |
| Any P1 finding (no P0) | `needs-changes` | Important issues present — should address before merging |
| Only P2/P3 findings or none | `safe` | No blocking issues — improvements suggested but not required |

**Deterministic guarantee:** Given the same set of findings, always produce the same verdict. No heuristics, no thresholds, no judgment calls.

**Conflict resolution:** If agents disagree on severity for an issue, use the most severe rating for verdict computation.

> **Why this works:** Deterministic verdicts are debuggable and predictable. The orchestrator doesn't need to "think" about whether issues are severe enough — the severity ratings from domain experts (fd-* agents) carry that judgment.

### Step 6: Structured Output — findings.json

Generate a machine-readable summary for programmatic access:

```json
{
  "reviewed": "2026-02-14T08:42:15Z",
  "input": "/root/projects/example/src/auth.ts",
  "input_type": "file",
  "agents_launched": ["fd-architecture", "fd-safety", "fd-correctness", "fd-quality"],
  "agents_completed": ["fd-architecture", "fd-safety", "fd-correctness", "fd-quality"],
  "agents_failed": [],
  "findings": [
    {
      "id": "P1-1",
      "severity": "P1",
      "agents": ["fd-architecture", "fd-safety"],
      "section": "Authentication",
      "title": "Session tokens stored in localStorage",
      "convergence": 2,
      "confidence": "medium"
    },
    {
      "id": "P0-1",
      "severity": "P0",
      "agents": ["fd-safety"],
      "section": "Input Validation",
      "title": "SQL injection vulnerability in user search",
      "convergence": 1,
      "confidence": "low",
      "note": "Single-agent finding — verify independently"
    }
  ],
  "improvements": [
    {
      "id": "IMP-1",
      "agents": ["fd-quality"],
      "section": "Naming",
      "title": "Inconsistent user vs account terminology",
      "convergence": 1
    },
    {
      "id": "IMP-2",
      "agents": ["fd-quality", "fd-correctness"],
      "section": "Error Handling",
      "title": "Add specific error messages for validation failures",
      "convergence": 2
    }
  ],
  "verdict": "risky",
  "early_stop": false,
  "content_routing_active": false,
  "synthesis_timestamp": "2026-02-14T08:45:32Z"
}
```

**Field definitions:**
- `reviewed`: ISO 8601 timestamp of review initiation
- `input_type`: `"file"` | `"diff"` | `"directory"` | `"document"`
- `agents_completed`: Agents that returned Valid or Malformed outputs (excludes Error/Missing)
- `agents_failed`: Agents that returned Error or Missing outputs
- `convergence`: Integer count of agents that reported this finding
- `confidence`: `"high"` (3+) | `"medium"` (2) | `"low"` (1)
- `early_stop`: Boolean — was Stage 2 skipped?
- `content_routing_active`: Boolean — did agents receive different content slices?

### Step 7: Human-Readable Summary — summary.md

Write to `{OUTPUT_DIR}/summary.md`:

```markdown
# Review Summary

**Verdict:** risky (4/4 agents completed, 0 failed)

**Input:** `/root/projects/example/src/auth.ts`
**Reviewed:** 2026-02-14 08:42
**Agents:** fd-architecture, fd-safety, fd-correctness, fd-quality

---

## Key Findings

### P0 — Critical Issues (1)
- **SQL injection vulnerability in user search** (1/4 agents: fd-safety)
  Single-agent finding — verify independently before proceeding.

### P1 — Important Issues (1)
- **Session tokens stored in localStorage** (2/4 agents: fd-architecture, fd-safety)
  High confidence — multiple agents agree.

---

## Issues to Address

- [ ] **P0** | SQL injection vulnerability in user search (Input Validation)
- [ ] **P1** | Session tokens stored in localStorage (Authentication)

---

## Improvements Suggested

- **Inconsistent user vs account terminology** (Naming) — fd-quality
- **Add specific error messages for validation failures** (Error Handling) — fd-quality, fd-correctness

---

## Section Heat Map

| Section | Issues | Agents Reporting |
|---------|--------|------------------|
| Input Validation | 1 | fd-safety |
| Authentication | 1 | fd-architecture, fd-safety |
| Naming | 1 | fd-quality |
| Error Handling | 1 | fd-quality, fd-correctness |

---

## Agent Reports

- [fd-architecture](/path/to/output/fd-architecture.md) — 3 findings
- [fd-safety](/path/to/output/fd-safety.md) — 2 findings
- [fd-correctness](/path/to/output/fd-correctness.md) — 1 improvement
- [fd-quality](/path/to/output/fd-quality.md) — 2 improvements

---

## Conflicts

*No severity conflicts detected.*
```

**Section ordering:**
1. Verdict + metadata
2. Key findings (grouped by severity, sorted by convergence descending)
3. Issues to address (checkbox format for action tracking)
4. Improvements suggested (non-blocking recommendations)
5. Section heat map (identify problem areas)
6. Agent reports (links to individual outputs)
7. Conflicts (if any severity disagreements)

### Step 8: Report to User

Present synthesis results in the following format:

```
Review complete — Verdict: risky

4/4 agents completed successfully (0 failed)

Critical Findings (P0):
- SQL injection vulnerability in user search (1/4 agents: fd-safety)
  ⚠️ Single-agent finding — verify independently

Important Findings (P1):
- Session tokens stored in localStorage (2/4 agents: fd-architecture, fd-safety)
  ✓ High confidence — multiple agents agree

Section Heat Map:
Authentication: 1 issue (2 agents)
Input Validation: 1 issue (1 agent)
Naming: 1 improvement (1 agent)
Error Handling: 1 improvement (2 agents)

Full report: /path/to/output/summary.md
Structured output: /path/to/output/findings.json
Individual reports: /path/to/output/{agent}.md
```

**Presentation rules:**
- Always show verdict + agent completion stats first
- Group findings by severity (P0 → P1 → P2 → P3)
- Include convergence counts with confidence indicators
- Flag single-agent P0/P1 findings as needing verification
- Provide file paths to all outputs
- If conflicts exist, note them explicitly

### Error Handling

| Scenario | Detection | Action |
|----------|-----------|--------|
| **Agent timeout** | Output file missing or empty | Check for `.partial` file — use partial results if available, otherwise create error stub: `{agent: "name", status: "timeout", findings: []}` |
| **Malformed output** | Findings Index unparseable | Prose fallback — extract findings from Summary/Issues sections using regex patterns |
| **All agents failed** | `agents_completed.length === 0` | Verdict: `error`. Report: "All agents failed — cannot compute verdict" |
| **No findings** | All agents returned safe verdicts | Verdict: `safe`. Still report improvements if any agent suggested them |
| **Partial agent set** | Early stop or slicing active | Adjust convergence M per finding. Report partial set in summary metadata |
| **Severity conflict** | Same issue, different severities | Use most severe rating. Flag conflict in findings.json and summary.md |

**Partial results contract:**
If an agent times out but wrote a `.partial` file:
- Parse available findings from partial output
- Tag with `"partial": true` in findings.json
- Exclude from convergence denominator M (agent didn't complete)
- Note in summary: "fd-architecture: partial results (timed out)"

> **Why this works:** Graceful degradation. One agent failure shouldn't block the entire synthesis. Partial results are better than no results — they may still contain actionable findings.

## Interflux Reference

**Implementation:**
- Synthesis algorithm: `skills/flux-drive/phases/synthesize.md` (365 lines)
- Orchestrator integration: `skills/flux-drive/phases/launch.md` (synthesis trigger)
- Convergence adjustment: Rules defined inline in this spec (Step 4) / `skills/flux-drive/phases/slicing.md` (implementation-level content routing)

**Contracts:**
- Output validation: `contracts/findings-index.md` (index format spec)
- findings.json schema: `skills/flux-drive/phases/synthesize.md` (Step 3.4a)
- Verdict rules: `contracts/findings-index.md` (spec) / `skills/flux-drive/phases/shared-contracts.md` (implementation)

**Domain integration:**
- Research escalation: `skills/flux-research/SKILL.md` (research findings merge into synthesis)
- Agent profiles: `config/flux-drive/domains/*.md` (domain-specific severity guidance)

## Conformance

**MUST:**
- Validate agent outputs before processing (Step 1)
- Parse Findings Index format per `contracts/findings-index.md` (Step 2)
- Implement deduplication across agent outputs (Step 3)
- Compute verdict deterministically from severity levels (Step 5)
- Generate structured output (findings.json or equivalent) (Step 6)
- Handle agent failures gracefully (error stubs, partial results) (Error Handling)

**SHOULD:**
- Track convergence and include counts in summary (Step 4)
- Adjust convergence for partial agent sets and content routing (Step 4)
- Generate human-readable summary (summary.md) (Step 7)
- Provide section heat map showing issue distribution (Step 7)
- Flag severity conflicts when agents disagree (Step 3)

**MUST NOT:**
- Skip output validation (Step 1) before processing agent findings
- Count failed or error-state agents in convergence denominator M
- Ignore severity conflicts when computing verdict — always use the most severe rating

**MAY:**
- Implement additional output formats beyond findings.json (Step 6)
- Provide interactive visualization of findings (Step 8)
- Cache deduplicated findings across multiple reviews (Step 3)
- Use fuzzy matching algorithms beyond Levenshtein distance (Step 3)
- Parallelize output validation and collection (Steps 1-2)
