# Track Dispatch — Steps 2 + 3

Steps 2 (fan-out track agent generation) and 3 (fan-out flux-drive reviews) run sequentially, with all active tracks parallelized inside each step.

## Step 2: Fan-Out — Generate Track Agent Sets in Parallel

Launch all active tracks in parallel using the Agent tool. Model per track depends on `QUALITY_MODE`:

| Track | economy | balanced | max |
|-------|---------|----------|-----|
| A (Adjacent) design | sonnet | sonnet | opus |
| B (Orthogonal) design | sonnet | sonnet | opus |
| C (Distant) design | sonnet | **opus** | opus |
| D (Esoteric) design | sonnet | **opus** | opus |

Each track subagent must (1) design agent specs via LLM, (2) save specs to JSON, (3) call generate-agents.py. All tracks run simultaneously.

### Common Preamble (included in every track prompt)

```
Target: {TARGET_DESC}
File/directory: {INPUT_PATH}

Severity reference:
- P0: Blocks other work or causes data loss/corruption. Drop everything.
- P1: Required to exit the current quality gate.
- P2: Degrades quality or creates maintenance burden.
- P3: Improvements and polish.

For each agent, output a JSON object with:
- name, focus, persona, decision_lens, review_areas (4-6 bullets),
  severity_examples (2-3 objects with severity/scenario/condition),
  success_hints (list of 2-4 strings), task_context, anti_overlap (list of 1-3 strings)

Design rules:
- Names: fd-{domain}-{concern}
- Each agent covers a DISTINCT aspect
- Review areas must be specific and actionable
- severity_examples must be concrete failure scenarios
- anti_overlap references other agents in this batch
- Always emit success_hints and anti_overlap as JSON arrays of short strings — never as a
  single paragraph. A string in these fields renders as character-exploded bullets.

Persona framing (important):
- Write each `persona` as a descriptive reviewer-framework, NOT first-person role
  adoption. Use "Apply the perspective of a <persona> — they care about X, measure Y,
  flag Z." Do NOT write "You are a <persona>..." — that phrasing combines poorly with
  multi-agent dispatch instructions and can trigger input-side safety classifiers.
- `task_context` should describe what is being reviewed and the review goal. Avoid
  strategic-influence verbs aimed at specific AI lab operators (e.g., "reach Anthropic
  researchers"). Prefer neutral framings: "document for external review", "surface
  evaluator-facing qualities", "identify improvements for public-facing surfaces".

Return ONLY a valid JSON array. No markdown.
```

### Track A: Adjacent (always active, 5 agents)

Additional prompt:
```
You are an expert at designing specialized code review agents.

Design 5 agents with DEEP EXPERTISE in the target's own domain and closely
adjacent fields. These agents should catch issues requiring specialist
knowledge of the target's technology, patterns, and failure modes.

Example (database migration system target):
- fd-migration-atomicity (transaction safety specialist)
- fd-schema-evolution (backward compatibility expert)
- fd-query-performance (execution plan analyst)
- fd-data-integrity (constraint and invariant guardian)
- fd-rollback-safety (deployment recovery specialist)
```

Specs path: `{PROJECT_ROOT}/.claude/flux-gen-specs/{SLUG}-adjacent.json`

### Track B: Orthogonal (active when TRACK_COUNT ≥ 3, 4 agents)

Additional prompt:
```
You are designing review agents from PARALLEL DISCIPLINES — fields at the same
abstraction level as the target but in different industries or domains.

Design 4 agents from disciplines operating at similar scale and complexity to
the target, but in a different professional context. These surface patterns
practitioners in adjacent-but-different fields take for granted.

Example (event-driven pipeline target):
- fd-broadcast-scheduling (television broadcast: real-time sequencing)
- fd-supply-chain-flow (logistics: pipeline throughput, bottleneck detection)
- fd-air-traffic-sequencing (ATC: priority queuing under safety constraints)
- fd-newsroom-workflow (editorial: multi-source aggregation, deadline pressure)

Selection constraints:
- Each domain must be a PROFESSIONAL DISCIPLINE with established best practices
- Same abstraction level as target (not micro/macro)
- Avoid pure-science domains (those go to distant/esoteric)
- Each agent must bring a specific operational pattern that maps to the target

Additional fields per agent:
- source_domain: the professional discipline
- distance_rationale: 1 sentence — how is this parallel but different?
- expected_isomorphisms: 1-2 sentences — what operational patterns transfer?
```

Specs path: `{PROJECT_ROOT}/.claude/flux-gen-specs/{SLUG}-orthogonal.json`

### Track C: Distant (active when TRACK_COUNT ≥ 2)

When TRACK_COUNT = 2, generate 5 agents. Otherwise generate 4.

Additional prompt:
```
You are exploring the semantic space of knowledge domains to find structural
isomorphisms relevant to a review target.

Design {4 or 5} agents from domains FAR FROM the target's field. These agents
apply structural patterns from unrelated disciplines to surface insights
invisible from within the target's domain.

Selection constraints:
- Each domain from a different field, era, or modality
- DO NOT use these AI-cliche domains: biology, military strategy, sports,
  information theory, thermodynamics, ecology, evolutionary biology, game theory,
  economic markets, ant colonies, neural networks, immune systems
- PREFER: pre-modern craft disciplines, physical processes at non-human scales,
  non-Western knowledge systems, professional practices with centuries of refinement
- Each domain must have rich internal structure that maps to the target's concerns
- No two agents may share the same parent discipline

Additional fields per agent:
- source_domain: the real-world knowledge domain
- distance_rationale: 1 sentence — why distant from the target?
- expected_isomorphisms: 1-2 sentences — what structural parallels do you expect?
```

Specs path: `{PROJECT_ROOT}/.claude/flux-gen-specs/{SLUG}-distant.json`

### Track D: Esoteric (active when TRACK_COUNT = 4, 3 agents)

Additional prompt:
```
You are pushing to the absolute frontier of the semantic space. Design agents
from the most UNEXPECTED, ALIEN knowledge domains you can find — domains no
practitioner in the target's field would think to consult.

Design 3 agents from domains at MAXIMUM SEMANTIC DISTANCE. These should provoke
genuine surprise. Think: domains separated by centuries, continents, scales of
observation. The structural isomorphisms should feel impossible until explained.

Selection constraints:
- Domains must be genuinely surprising — if a software engineer would say
  "oh yeah, that's a common analogy," REJECT it and go further
- Each domain from a different civilization, era, or physical scale
- Include at least one PRE-INDUSTRIAL and one NON-WESTERN domain
- The structural mapping must be SPECIFIC (name the mechanism), not metaphorical
- No overlap with domains in other tracks

Additional fields per agent:
- source_domain: the knowledge domain (name the specific tradition or practice)
- distance_rationale: 1 sentence — why would no one think to look here?
- expected_isomorphisms: 1-2 sentences — what specific mechanism transfers?
```

Specs path: `{PROJECT_ROOT}/.claude/flux-gen-specs/{SLUG}-esoteric.json`

### After all tracks complete

Each subagent calls generate-agents.py:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py {PROJECT_ROOT} --from-specs <specs-file> --mode=skip-existing --json
```

Display per-track results:
```
Track A (Adjacent):   {N} domain-expert agents
Track B (Orthogonal): {N} parallel-discipline agents     [if active]
Track C (Distant):    {N} distant-domain agents
Track D (Esoteric):   {N} frontier-domain agents          [if active]
Total: {sum} agents generated
```

If any track fails, report which failed and proceed with the surviving tracks.

## Step 3: Fan-Out — Run Flux-Drive Reviews in Parallel

Launch one flux-drive review per active track using the Agent tool, all in parallel with `run_in_background: true`. Model per track depends on `QUALITY_MODE`:

| Track | economy | balanced | max |
|-------|---------|----------|-----|
| A (Adjacent) review | sonnet | **opus** | opus |
| B (Orthogonal) review | sonnet | sonnet | opus |
| C (Distant) review | sonnet | sonnet | opus |
| D (Esoteric) review | sonnet | sonnet | opus |

For each active track, launch an Agent tool with the appropriate model. Use this prompt template **verbatim** — do NOT embellish with strategic-influence framing (e.g., "reach AI labs", "ruthless prioritization", or naming specific AI lab operators as targets). Those combinations, together with multi-agent dispatch instructions and first-person persona adoption in agent files, can trigger server-side input classifiers and produce synthetic Usage Policy refusals.

```
Run a flux-drive review of {INPUT_PATH}.

Use the `interflux:flux-engine` skill on {INPUT_PATH}. This will auto-discover
the project agents (including the newly generated {track_name}-domain agents)
and run the full triage → launch → synthesize pipeline.

Focus on {track_focus_description}. The generated agents for this track
({list agent names}) should be triaged as Project Agents.
```

Track focus descriptions:
- **Track A (Adjacent):** "domain-expert findings requiring specialist knowledge"
- **Track B (Orthogonal):** "operational patterns from parallel professional disciplines"
- **Track C (Distant):** "structural isomorphisms from distant knowledge domains"
- **Track D (Esoteric):** "frontier patterns from maximally unexpected domains"

**Wait for all reviews to complete.** Display progress per track:
```
✓ Track A (Adjacent) review complete: {N} findings
✓ Track B (Orthogonal) review complete: {N} findings     [if active]
✓ Track C (Distant) review complete: {N} findings
✓ Track D (Esoteric) review complete: {N} findings        [if active]
```
