# Track Synthesis — Step 4

Cross-track synthesis fans the per-track flux-drive findings back into a single ranked report. Convergent findings (same issue surfaced from independent reasoning paths) are the highest-confidence signal.

## Read findings

Each per-track flux-drive run writes findings to `docs/research/flux-drive/{INPUT_STEM}/` (or per-track subdirectories like `interflux-roadmap-track-a/` if the track agents specified output dirs in their dispatch prompts). Read all `.md` finding files across the involved track directories.

## Launch synthesis subagent

Model per `QUALITY_MODE`: **economy** → sonnet, **balanced** → opus, **max** → opus.

Prompt template (verbatim):
```
You are synthesizing findings from a multi-track deep review.

Target: {TARGET_DESC}
File: {INPUT_PATH}

The review ran {TRACK_COUNT} parallel tracks at increasing semantic distance:
{for each active track:}
- Track {letter} ({name}): {N} agents — {distance_description}
  Agents: {list names + focus [+ source_domain for B/C/D]}

Findings from all agents:
{all findings content from per-track output dirs}

Produce a unified synthesis with these sections:

## Critical Findings (P0/P1)
Issues requiring immediate action. For each:
- The finding and which agent(s) surfaced it
- Which track(s) it came from (adjacent, orthogonal, distant, esoteric)
- Concrete fix recommendation

## Cross-Track Convergence
Findings that appeared independently in 2+ tracks — the highest-confidence
signals because they were discovered through independent reasoning paths at
different semantic distances. For each convergent finding:
- Which tracks independently surfaced it (name the agents from each track)
- How each track's perspective frames the same issue differently
- The convergence score: how many independent tracks found it (2/2, 2/3, 3/4, etc.)

Rank convergent findings by convergence score (more tracks = higher confidence).

## Domain-Expert Insights (Track A)
The most valuable findings from adjacent-domain specialists requiring deep
domain knowledge to identify. Group by theme.

## Parallel-Discipline Insights (Track B) [if Track B active]
Operational patterns surfaced by orthogonal-domain agents — professional
practices from parallel disciplines that map to the target's workflow.
For each: source discipline, specific practice, how it maps.

## Structural Insights (Track C)
Novel patterns surfaced by distant-domain agents — mechanisms from other fields
that reveal something about the target's architecture. For each:
- Source domain and structural isomorphism
- How it maps to the target
- Whether it suggests a concrete improvement or is an open question

## Frontier Patterns (Track D) [if Track D active]
The most surprising patterns from esoteric domains. These should provoke genuine
"I never would have thought of that" reactions. For each:
- Source domain and why it is unexpected
- The specific mechanism and how it maps
- Whether this opens a new design direction or refines an existing one

## Synthesis Assessment
- Overall quality of the target (1-2 sentences)
- Highest-leverage improvement (the single change with the most impact)
- Surprising finding (something no single track would surface alone)
- Semantic distance value: did the outer tracks (C/D) contribute insights
  qualitatively different from inner tracks (A/B), or did they mostly restate
  the same issues in different vocabulary?

Write in direct, technical prose. Name agents when attributing findings.
Prioritize convergent findings (found across multiple tracks) over single-track findings.
```

## Output

Write synthesis to `{PROJECT_ROOT}/docs/research/flux-review/{SLUG}/{DATE}-synthesis.md` with frontmatter:

```yaml
---
artifact_type: review-synthesis
method: flux-review
target: "{INPUT_PATH}"
target_description: "{TARGET_DESC}"
tracks: {TRACK_COUNT}
track_a_agents: [{Track A names}]
track_b_agents: [{Track B names}]  # if active
track_c_agents: [{Track C names}]
track_d_agents: [{Track D names}]  # if active
date: {DATE}
---
```

Include any caveats discovered during synthesis (e.g., a track that ran inline-personas instead of true parallel subagents, or a track that timed out and didn't contribute findings).
