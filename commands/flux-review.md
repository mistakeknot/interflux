---
name: flux-review
description: "Dual-track deep review — generates domain-adjacent AND domain-distant agents in parallel, runs flux-drive with each set, then synthesizes across both tracks for maximum coverage"
user-invocable: true
codex-aliases: [flux-review]
argument-hint: "<path to file or directory>"
---

# Flux-Review — Dual-Track Deep Review

Run a two-track fan-out/fan-in review that combines **domain-adjacent** analysis (closely related expertise) with **domain-distant** analysis (orthogonal, esoteric knowledge domains) for maximum coverage. Each track generates specialized agents via flux-gen, reviews the target via flux-drive, then a synthesis step merges findings across both tracks.

## Why Two Tracks?

Domain-adjacent agents catch issues that require deep expertise in the target's own field (migration safety, API contract violations, concurrency bugs). Domain-distant agents surface structural patterns invisible from within the field — mechanisms from perfumery, paleography, physical oceanography, etc. that map to the target's architecture. Together they produce insights neither track can find alone.

## Step 0: Parse Arguments

Parse `$ARGUMENTS`:
- Extract the file or directory path (required)
- If empty, use AskUserQuestion to get the path

Derive:
```
INPUT_PATH    = <the path provided>
PROJECT_ROOT  = <nearest ancestor directory containing .git, or directory of INPUT_PATH>
TARGET_DESC   = <1-line description derived from reading the file/directory>
SLUG          = <kebab-case from TARGET_DESC, max 40 chars>
DATE          = <YYYY-MM-DD>
```

Read the target (first 200 lines if file, README/CLAUDE.md if directory) to derive TARGET_DESC.

---

## Step 1: Confirm

Use **AskUserQuestion**:

```
Dual-track deep review of: {INPUT_PATH}
Target: {TARGET_DESC}

  Track A (Adjacent): 5 domain-expert agents → flux-drive review
  Track B (Distant):  5 esoteric-domain agents → flux-drive review
  Synthesis: Cross-track findings merged into unified analysis

This will generate up to 10 agents and run 2 flux-drive reviews.
Estimated context: ~200k tokens.

Proceed?
```

Options:
- "Proceed (Recommended)"
- "Adjacent track only (skip distant)"
- "Cancel"

---

## Step 2: Fan-Out — Generate Both Agent Sets in Parallel

Launch **two Agent tool calls in parallel** (both `model: sonnet`):

### Track A: Domain-Adjacent Agents

Prompt for Agent tool subagent:

```
You are an expert at designing specialized code review agents. Given a target,
design 5 focused review agents that provide deep domain-expert analysis.

Target: {TARGET_DESC}
File/directory: {INPUT_PATH}

Severity reference:
- P0: Blocks other work or causes data loss/corruption. Drop everything.
- P1: Required to exit the current quality gate.
- P2: Degrades quality or creates maintenance burden.
- P3: Improvements and polish.

Design 5 agents with DEEP EXPERTISE in the target's own domain and closely
adjacent fields. These agents should catch issues that require specialist
knowledge of the target's technology, patterns, and failure modes.

For example, if reviewing a database migration system:
- fd-migration-atomicity (transaction safety specialist)
- fd-schema-evolution (backward compatibility expert)
- fd-query-performance (execution plan analyst)
- fd-data-integrity (constraint and invariant guardian)
- fd-rollback-safety (deployment recovery specialist)

For each agent, output a JSON object with:
- name, focus, persona, decision_lens, review_areas (4-6 bullets),
  severity_examples (2-3 objects with severity/scenario/condition),
  success_hints, task_context, anti_overlap

Design rules:
- Names: fd-{domain}-{concern}
- Each agent covers a DISTINCT aspect of the domain
- Review areas must be specific and actionable
- severity_examples must be concrete failure scenarios
- anti_overlap references other agents in this batch

Return ONLY a valid JSON array. No markdown.
```

This subagent should write the specs to a temp file AND call generate-agents.py:

```
Save specs to: {PROJECT_ROOT}/.claude/flux-gen-specs/{SLUG}-adjacent.json
Generate: python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py {PROJECT_ROOT} --from-specs <specs-file> --mode=skip-existing --json
```

### Track B: Domain-Distant Agents

Prompt for Agent tool subagent:

```
You are exploring the semantic space of knowledge domains to find structural
isomorphisms relevant to a review target.

Target: {TARGET_DESC}
File/directory: {INPUT_PATH}

Severity reference:
- P0: Blocks other work or causes data loss/corruption. Drop everything.
- P1: Required to exit the current quality gate.
- P2: Degrades quality or creates maintenance burden.
- P3: Improvements and polish.

Design 5 review agents from domains MAXIMALLY DISTANT from the target's own field.
These agents apply structural patterns from unrelated disciplines to surface
insights invisible from within the target's domain.

Selection constraints:
- Each domain must come from a different field, era, or modality
- DO NOT use common AI-analogy domains: biology, military strategy, sports,
  information theory, thermodynamics, ecology, evolutionary biology, game theory,
  economic markets, ant colonies, neural networks, immune systems
- PREFER: pre-modern craft disciplines, physical processes at non-human scales,
  non-Western knowledge systems, professional practices with centuries of refinement,
  performing arts with real-time coordination, material sciences, navigation traditions
- Each domain must have rich internal structure that maps to the target's concerns

For each agent, output a JSON object with:
- name, focus, persona, decision_lens, review_areas (4-6 bullets),
  severity_examples (2-3 objects with severity/scenario/condition),
  success_hints, task_context, anti_overlap
- source_domain: the real-world knowledge domain
- distance_rationale: 1 sentence — why is this distant from the target?
- expected_isomorphisms: 1-2 sentences — what structural parallels do you expect?

Design rules:
- Names: fd-{domain-noun}-{concern} (e.g., fd-perfumery-accord, fd-tidal-resonance)
- severity_examples must be concrete, not restatements of P0/P1 definitions
- expected_isomorphisms must name specific mechanisms
- No two agents may share the same parent discipline

Return ONLY a valid JSON array. No markdown.
```

This subagent should write specs AND generate agents similarly:

```
Save specs to: {PROJECT_ROOT}/.claude/flux-gen-specs/{SLUG}-distant.json
Generate: python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py {PROJECT_ROOT} --from-specs <specs-file> --mode=skip-existing --json
```

**Wait for both subagents to complete.** Display results:

```
Track A (Adjacent): Generated {N} domain-expert agents
  - fd-{name}: {focus}
  ...

Track B (Distant): Generated {M} agents from distant domains
  - fd-{name}: {focus} [source: {source_domain}]
  ...
```

If either track fails, report the failure and proceed with the successful track only.

---

## Step 3: Fan-Out — Run Flux-Drive Reviews in Parallel

Launch **two flux-drive reviews in parallel** using the Agent tool. Each agent runs flux-drive as a skill invocation.

### Track A Review

Launch an Agent tool (subagent_type: general-purpose, run_in_background: true):

```
Run a flux-drive review of {INPUT_PATH}.

Use the `/interflux:flux-drive {INPUT_PATH}` skill. This will auto-discover
the project agents (including the newly generated adjacent-domain agents)
and run the full triage → launch → synthesize pipeline.

Focus on domain-expert findings. The generated adjacent-domain agents
({list Track A agent names}) should be triaged as Project Agents.
```

### Track B Review

Launch an Agent tool (subagent_type: general-purpose, run_in_background: true):

```
Run a flux-drive review of {INPUT_PATH}.

Use the `/interflux:flux-drive {INPUT_PATH}` skill. This will auto-discover
the project agents (including the newly generated distant-domain agents)
and run the full triage → launch → synthesize pipeline.

Focus on cross-domain structural insights. The generated distant-domain agents
({list Track B agent names}) should be triaged as Project Agents.
```

**Wait for both reviews to complete.**

Display progress as each completes:
```
✓ Track A review complete: {N} findings
✓ Track B review complete: {M} findings
```

---

## Step 4: Fan-In — Cross-Track Synthesis

Read findings from both flux-drive runs. The reviews write findings to `docs/research/flux-drive/{INPUT_STEM}/`.

Since both runs write to the same output directory, the findings from all agents across both tracks will be in that directory. Read all `.md` files from there.

Launch a **Sonnet** subagent (Agent tool, `model: sonnet`) for synthesis:

```
You are synthesizing findings from a dual-track deep review.

Target: {TARGET_DESC}
File: {INPUT_PATH}

The review ran two parallel tracks:
- Track A (Domain-Adjacent): {N} specialist agents with deep domain expertise
- Track B (Domain-Distant): {M} agents applying structural patterns from distant fields

Track A agents: {list names + focus}
Track B agents: {list names + focus + source_domain}

Findings from all agents:
{all findings content from docs/research/flux-drive/{INPUT_STEM}/}

Produce a unified synthesis with these sections:

## Critical Findings (P0/P1)
Issues requiring immediate action. For each:
- The finding and which agent(s) surfaced it
- Whether it was found by adjacent agents, distant agents, or both (convergence)
- Concrete fix recommendation

## Cross-Track Convergence
Findings that appeared independently in both tracks — an adjacent-domain expert
AND a distant-domain agent flagged the same structural issue from different angles.
These have the highest confidence because they were discovered through independent
reasoning paths. Name both agents and explain how their perspectives converge.

## Domain-Expert Insights (Track A)
The most valuable findings from adjacent-domain specialists that require deep
domain knowledge to identify. Group by theme.

## Structural Insights (Track B)
Novel patterns surfaced by distant-domain agents — mechanisms from other fields
that reveal something about the target. For each:
- The source domain and structural isomorphism
- How it maps to the target
- Whether it suggests a concrete improvement or is an open question

## Synthesis Assessment
- Overall quality of the target (1-2 sentences)
- Highest-leverage improvement (the single change that would have the most impact)
- Surprising finding (something neither track alone would likely surface)

Write in direct, technical prose. Name agents when attributing findings.
Prioritize convergent findings (found by both tracks) over single-track findings.
```

Write synthesis to `{PROJECT_ROOT}/docs/research/flux-review/{SLUG}/{DATE}-synthesis.md` with frontmatter:

```yaml
---
artifact_type: review-synthesis
method: flux-review
target: "{INPUT_PATH}"
target_description: "{TARGET_DESC}"
track_a_agents: [{Track A names}]
track_b_agents: [{Track B names}]
date: {DATE}
---
```

---

## Step 5: Report

```
Dual-track review complete for: {INPUT_PATH}

Track A (Adjacent): {N} agents, {A_findings} findings
Track B (Distant):  {M} agents, {B_findings} findings
Cross-track convergence: {convergent_count} findings appeared in both tracks

Synthesis: docs/research/flux-review/{SLUG}/{DATE}-synthesis.md

Agent specs:
  Adjacent: .claude/flux-gen-specs/{SLUG}-adjacent.json
  Distant:  .claude/flux-gen-specs/{SLUG}-distant.json

To rerun with existing agents: /flux-drive {INPUT_PATH}
To regenerate agents: /flux-gen --from-specs .claude/flux-gen-specs/{SLUG}-adjacent.json
```

---

## Notes

- Both tracks run flux-drive independently — they share the same triage and scoring pipeline but operate on different agent pools
- Cross-track convergence (same issue found by both an adjacent and distant agent) is the highest-confidence signal — these findings are triangulated from independent reasoning paths
- The distant-domain agents are generated with the same anti-clustering instruction as `/flux-explore` (13 blocked AI-analogy domains)
- Track specs are saved separately for independent regeneration
- If one track fails, the command degrades gracefully to single-track review
- Token cost is approximately 2× a standard flux-drive review (~200k tokens total)
