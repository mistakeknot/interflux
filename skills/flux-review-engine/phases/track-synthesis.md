# Track Synthesis — Step 4

Cross-track synthesis fans the per-track flux-drive findings back into a single ranked report. Convergent findings (same issue surfaced from several tracks) are a strong signal **only to the extent the tracks are independent**. Tracks differ in semantic distance, but their reviews usually run on one base model family (sonnet/opus per `track-dispatch.md`), so same-family agreement is correlated evidence, not independent corroboration (issue #52). Convergence is therefore ranked and labelled by **family-weighted convergence** computed deterministically by `scripts/cross_track_convergence.py` — never by raw track head-count. See `docs/spec/core/synthesis.md` Step 4b.

## Read findings

Each per-track flux-drive run writes findings to its own **disjoint** directory: `{PROJECT_ROOT}/docs/research/flux-review/{SLUG}/track-{letter}/` (the explicit `--output-dir` passed in Step 3 — see `track-dispatch.md` § Per-track output isolation, issue #6). Read all `.md` finding files across the active track directories (`track-a/`, `track-b/`, `track-c/`, `track-d/` as applicable). Within each track directory the finding files are run-scoped (`{agent}.{run-uuid}.md`); read them all — each track dir is a single flux-drive run, so there is exactly one run-uuid per track directory.

Also read each track's `track-{letter}/findings.json`. Its per-finding `provenance[agent].model_family` (or flat `model_family`) is orchestrator dispatch metadata and is the **only** source of truth for which model family produced a track's findings. Collect the distinct families per track for the prompt below. A track whose findings.json carries no provenance is assumed to be `convergence.default_model_family` from `config/flux-review/defaults.yaml` (`claude`) — missing provenance never counts as an independent family.

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
  Model families: {distinct model_family values from track-{letter}/findings.json provenance}

Findings from all agents:
{all findings content from per-track output dirs}

Produce a unified synthesis with these sections:

## Critical Findings (P0/P1)
Issues requiring immediate action. For each:
- The finding and which agent(s) surfaced it
- Which track(s) it came from (adjacent, orthogonal, distant, esoteric)
- Concrete fix recommendation

## Cross-Track Convergence
Findings that appeared in 2+ tracks. Give each convergent finding a stable id
(XT-1, XT-2, ...) and for each:
- Which tracks surfaced it (name the agents from each track)
- How each track's perspective frames the same issue differently
- The raw track count (2/2, 2/3, 3/4, etc.)

Do NOT assign a confidence label (High/Medium/Low) and do NOT rank by raw track
count. Agreement between tracks that share a model family is correlated, not
independent; confidence is computed afterwards from model-family provenance and
inserted under this heading. Order findings by id.

Also write {REVIEW_DIR}/cross-track-convergence.json with one cluster per
convergent finding (do not include model families — they are read from
provenance, not from this file):
{"clusters": [{"id": "XT-1", "title": "<short title>",
               "tracks": {"<letter>": [{"agent": "<agent name>", "finding_id": "<id in that track's findings.json>"}]}}]}

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
Prioritize convergent findings (found across multiple tracks) over single-track
findings, but describe their strength as "corroborated across N tracks", not as
"independently confirmed", unless the tracks span different model families.
```

`{REVIEW_DIR}` = `{PROJECT_ROOT}/docs/research/flux-review/{SLUG}`.

## Output

Write synthesis to `{PROJECT_ROOT}/docs/research/flux-review/{SLUG}/{DATE}-synthesis.md`, then compute weighted convergence and splice it in (issue #52):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cross_track_convergence.py \
  {REVIEW_DIR} --write-synthesis {REVIEW_DIR}/{DATE}-synthesis.md
```

The script reads `cross-track-convergence.json` plus each `track-{letter}/findings.json`, writes `cross-track-convergence.scored.json`, and inserts (or replaces, between `<!-- cross-track-convergence:begin/end -->` markers) a table under `## Cross-Track Convergence` with each finding's raw track count, model families, weighted convergence, and confidence label. When every convergent track shares one model family it also inserts the standing **correlated-convergence caveat**. The label in that table is the only confidence label for cross-track convergence; a finding found by 3/3 tracks of one family prints as `Correlated`, never `High`. If the sidecar is missing (exit 2), state "Cross-track convergence confidence not computed" under the heading instead of inventing labels.

Use `convergent_count` and `single_family` from `cross-track-convergence.scored.json` for the frontmatter below and for the Step 5 report.

Frontmatter:

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
convergent_findings: {convergent_count}
convergence_model_families: [{convergent_model_families}]
convergence_single_family: {single_family}   # true => correlated-convergence caveat present
date: {DATE}
---
```

Include any caveats discovered during synthesis — always including the correlated-convergence caveat when `single_family` is true — (e.g., a track that ran inline-personas instead of true parallel subagents, or a track that timed out and didn't contribute findings).
