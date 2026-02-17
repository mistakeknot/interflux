---
name: flux-research
description: Use when researching a topic with multi-agent analysis — triages relevant research agents, dispatches in parallel, synthesizes answer with source attribution
---

# Flux Research — Multi-Agent Research Orchestration

You are executing the flux-research skill. This skill answers research questions by dispatching **only relevant** research agents from the roster, collecting their findings in parallel, and synthesizing a unified answer with source attribution. Follow each phase in order. Do NOT skip phases.

## Input

The user provides a research question as an argument. If no question is provided, ask for one using AskUserQuestion.

```
RESEARCH_QUESTION = <the question the user provided>
PROJECT_ROOT = <git root of the current working directory>
OUTPUT_DIR = {PROJECT_ROOT}/docs/research/flux-research/{query-slug}
```

Where `{query-slug}` is the research question converted to kebab-case (max 50 chars, alphanumeric + hyphens only).

---

## Phase 1: Triage

### Step 1.0: Domain detection (reuse from flux-drive)

Check for domain context that can sharpen research queries:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/detect-domains.py --check-stale 2>/dev/null || true
```

If a `{PROJECT_ROOT}/.claude/flux-drive.yaml` cache exists, read the detected domains. For each detected domain, load `${CLAUDE_PLUGIN_ROOT}/config/flux-drive/domains/{domain-name}.md` and extract the `## Research Directives` section (if present).

**Fallback**: If no domains detected or no Research Directives sections exist, skip domain injection — agents run with the raw query only.

### Step 1.1: Build Query Profile

Analyze the research question to determine:

```yaml
query_profile:
  type: <one of: onboarding, how-to, why-is-it, what-changed, best-practice, debug-context, exploratory>
  keywords: [list of key terms extracted from the question]
  scope: <narrow | medium | broad>
  project_domains: [from Step 1.0, if any]
  estimated_depth: <quick | standard | deep>
```

**Type detection heuristics:**
- "how do I..." / "what's the best way to..." → `how-to`
- "why does..." / "why is..." → `why-is-it`
- "what changed..." / "when did..." → `what-changed`
- "best practice for..." / "conventions for..." → `best-practice`
- "help me understand this codebase..." / "how is this organized..." → `onboarding`
- "I'm debugging..." / "context for this bug..." → `debug-context`
- No clear pattern → `exploratory`

**Depth estimation:**
- `quick` (30s per agent): simple factual lookups, single-source answers
- `standard` (2min per agent): multi-source synthesis, pattern matching
- `deep` (5min per agent): comprehensive survey, cross-referencing, analysis

### Step 1.2: Score agents

Score each research agent on a 3-point scale using the query-type → agent affinity table:

| Query Type | Primary (score=3) | Secondary (score=2) | Skip (score=0) |
|---|---|---|---|
| onboarding | repo-research-analyst | learnings-researcher, framework-docs-researcher | best-practices-researcher, git-history-analyzer |
| how-to | best-practices-researcher, framework-docs-researcher | learnings-researcher | repo-research-analyst, git-history-analyzer |
| why-is-it | git-history-analyzer, repo-research-analyst | learnings-researcher | best-practices-researcher, framework-docs-researcher |
| what-changed | git-history-analyzer | repo-research-analyst | best-practices-researcher, framework-docs-researcher, learnings-researcher |
| best-practice | best-practices-researcher | framework-docs-researcher, learnings-researcher | repo-research-analyst, git-history-analyzer |
| debug-context | learnings-researcher, git-history-analyzer | repo-research-analyst, framework-docs-researcher | best-practices-researcher |
| exploratory | repo-research-analyst, best-practices-researcher | git-history-analyzer, framework-docs-researcher, learnings-researcher | — |

**Domain bonus**: If a detected domain has Research Directives for `best-practices-researcher` or `framework-docs-researcher`, add +1 to their score (these agents benefit most from domain-specific search terms).

**Selection**: Launch all agents with score >= 2. Agents with score 0 are skipped entirely.

### Step 1.3: User confirmation

Present the triage result via **AskUserQuestion**:

```yaml
AskUserQuestion:
  question: "Research plan for: '{RESEARCH_QUESTION}'. Query type: {type}. Launching {N} agents ({agent_names}). Estimated depth: {estimated_depth}. Proceed?"
  header: "Research"
  options:
    - label: "Launch (Recommended)"
      description: "Dispatch {N} agents in parallel for {estimated_depth} research"
    - label: "Edit agents"
      description: "Add or remove specific agents before launch"
    - label: "Cancel"
      description: "Abort research"
```

If user selects "Edit agents", present a multi-select AskUserQuestion with all 5 agents and let them toggle.

If user selects "Cancel", stop immediately.

---

## Phase 2: Launch

### Step 2.0: Prepare output directory

```bash
mkdir -p {OUTPUT_DIR}
find {OUTPUT_DIR} -maxdepth 1 -type f \( -name "*.md" -o -name "*.md.partial" \) -delete
```

### Step 2.1: Build per-agent prompts

For each selected agent, construct a research prompt:

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

### Step 2.2: Parallel dispatch

Launch all selected agents via Task tool with `run_in_background: true`:

```
Task(interflux:research:{agent-name}):
  prompt: {constructed prompt from Step 2.1}
  run_in_background: true
```

**Agent invocation:**

| Agent | subagent_type |
|-------|--------------|
| best-practices-researcher | interflux:research:best-practices-researcher |
| framework-docs-researcher | interflux:research:framework-docs-researcher |
| git-history-analyzer | interflux:research:git-history-analyzer |
| learnings-researcher | interflux:research:learnings-researcher |
| repo-research-analyst | interflux:research:repo-research-analyst |

### Step 2.3: Monitor completion

**Timeouts by depth:**
| Depth | Per-agent timeout |
|-------|------------------|
| quick | 30 seconds |
| standard | 2 minutes |
| deep | 5 minutes |

**Polling loop** (every 15 seconds):
1. Check `{OUTPUT_DIR}/` for `.md` files (not `.md.partial`)
2. Report progress:
   ```
   ✅ learnings-researcher (12s)
   ⏳ best-practices-researcher
   ⏳ framework-docs-researcher
   [1/3 agents complete]
   ```
3. If all expected `.md` files exist, stop polling
4. After timeout, report any agents still pending

**Completion verification:**
1. For agents that didn't complete, check background task output for errors
2. Create error stubs for failed agents:
   ```markdown
   ### Sources
   (none — agent failed)
   ### Findings
   Agent {name} did not complete within timeout.
   ### Confidence
   No findings available.
   ### Gaps
   This agent's entire domain is a gap in the research.
   ```
3. Clean up `.md.partial` files

---

## Phase 3: Synthesize

### Step 3.1: Delegate to Synthesis Subagent

**Do NOT read agent output files yourself.** Delegate ALL collection, merging, ranking, and verdict writing to a synthesis subagent. This keeps agent prose entirely out of the host context.

Launch the **intersynth research synthesis agent** (foreground, not background — you need its result):

```
Task(intersynth:synthesize-research):
  prompt: |
    OUTPUT_DIR={OUTPUT_DIR}
    VERDICT_LIB={CLAUDE_PLUGIN_ROOT}/../../hub/clavain/hooks/lib-verdict.sh
    RESEARCH_QUESTION={RESEARCH_QUESTION}
    QUERY_TYPE={type}
    ESTIMATED_DEPTH={estimated_depth}
```

The intersynth agent reads all research agent output files, merges findings with source attribution, ranks sources, writes verdicts, and returns a compact answer. It writes `{OUTPUT_DIR}/synthesis.md`.

After the synthesis subagent returns:
1. Its return value is the compact answer (~5-10 lines) — display this immediately as the quick answer
2. Read `{OUTPUT_DIR}/synthesis.md` for the full report to present to the user
3. The host agent never touched any individual agent output file

### Step 3.2-3.4: (Handled by intersynth)

Source ranking, merging, conflict resolution, and report generation are performed by the intersynth synthesis agent.

### Step 3.5: Present unified answer

Read `{OUTPUT_DIR}/synthesis.md` and present to user. This file was written by the intersynth agent.

### Output Summary

When complete, display:

```
Research complete!

Output: {OUTPUT_DIR}/synthesis.md
Agents: {N} dispatched, {M} completed, {K} failed
Sources: {total} ({internal} internal, {external} external)

Key answer: [1-2 sentence summary]
```
