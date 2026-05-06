---
name: flux-explore
description: Autonomous multi-round semantic exploration — agents from progressively distant knowledge domains, synthesize cross-domain isomorphisms.
user-invocable: true
codex-aliases: [flux-explore]
argument-hint: "<target description> [--rounds=3] [--agents-per-round=5] [--teams]"
---

# Flux-Explore — Autonomous Semantic Space Exploration

Generate review agents from progressively more distant knowledge domains and synthesize cross-domain structural isomorphisms. Wraps `/flux-gen` in a multi-round loop where each round draws from domains maximally distant from all prior coverage.

## Step 0: Parse Arguments

Parse `$ARGUMENTS`:
- Extract `--rounds=N` (default: 3, max: 5)
- Extract `--agents-per-round=N` (default: 5, max: 7)
- Extract `--teams` (boolean flag): if present, set `TEAMS_REQUESTED=true`; default `false`. Opts the synthesis pass into Claude Code agent-teams cross-domain debate mode (experimental, requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` and `claude` >= 2.1.32). When unavailable at runtime, falls back transparently to the single-Sonnet synthesis path.
- Remaining text is the target description

If target is empty, build a default:
1. Read project root for README.md, build files, and CLAUDE.md
2. Derive: `"Exploration of {PROJECT_ROOT basename}: {1-line project description}"`

Derive `{slug}` from target (e.g., `interflux-architecture`, `garden-salon-design`).

---

## Step 1: Display Plan and Proceed

Display the exploration plan:

```
Semantic space exploration for: {target}

Plan: {rounds} rounds × {agents_per_round} agents = up to {rounds × agents_per_round} agent files

  Round 1: Domain-appropriate agents (standard flux-gen design)
  Rounds 2-{rounds}: Maximally distant domains with structural isomorphism search
  Final: Cross-domain synthesis document

Specs saved per round to .claude/flux-gen-specs/{slug}-round-N.json
Agents written to .claude/agents/fd-*.md
```

**Auto-proceed (default):** Proceed directly to Step 2.

**Interactive mode** (`--interactive` flag): Use AskUserQuestion to confirm:
- "Proceed with {rounds} rounds (Recommended)"
- "Adjust rounds/agents"
- "Cancel"

If "Adjust", use AskUserQuestion to get new rounds and agents_per_round values.

---

## Step 2: Round 1 — Seed

Display: `🔬 Round 1/{rounds}: Generating domain-appropriate agents for "{target}"...`

Launch a **Sonnet** subagent (Agent tool, `model: sonnet`) with the **standard flux-gen design prompt** from `/flux-gen` Step 1, including severity_examples. The task description is `{target}`.

Parse JSON response. On failure, report and abort.

**Save specs** to `{PROJECT_ROOT}/.claude/flux-gen-specs/{slug}-round-1.json` using Write tool.

**Generate agents:**

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py {PROJECT_ROOT} --from-specs /tmp/flux-explore-round-1.json --mode=skip-existing --json
```

Parse report. Record generated agent names + focus descriptions in an accumulator list:

```
accumulated_agents = [
  { name: "fd-xyz", focus: "...", source_domain: "standard" },
  ...
]
```

Display per-agent results:
```
Round 1 complete: {N} agents generated
  - fd-{name1}: {focus}
  - fd-{name2}: {focus}
  ...
```

If any agents were skipped (already exist), display: `NOTE: {name} already exists, skipped (use --mode=force to refresh)`

---

## Step 3: Rounds 2..N — Explore

For each round R from 2 to `{rounds}`:

Display: `🌐 Round {R}/{rounds}: Exploring distant domains (coverage: {len(accumulated)} agents)...`

Launch a **Sonnet** subagent (Agent tool, `model: sonnet`) with this prompt:

```
You are exploring the semantic space of knowledge domains to find structural
isomorphisms relevant to: {target}

Domains already covered (do not repeat these or closely adjacent fields):
{for each agent in accumulated_agents:}
  - {name}: {focus} (source: {source_domain})

Severity reference (use these exact definitions when designing severity_examples):
- P0: Blocks other work or causes data loss/corruption. Drop everything.
- P1: Required to exit the current quality gate. If this doesn't ship, the version doesn't ship.
- P2: Degrades quality or creates maintenance burden.
- P3: Improvements and polish.

Design {agents_per_round} review agents from domains MAXIMALLY DISTANT from all
prior coverage.

Selection constraints:
- Each domain must come from a different field, era, or modality than any prior domain
- DO NOT use common AI-analogy domains: biology, military strategy, sports, information
  theory, thermodynamics, ecology, evolutionary biology, game theory, economic markets,
  ant colonies, neural networks, immune systems
- PREFER: pre-modern craft disciplines, physical processes at non-human scales,
  non-Western knowledge systems, professional practices with centuries of refinement,
  performing arts with real-time coordination, material sciences, navigation traditions
- Each domain must have rich internal structure that maps to the target's concerns
- No two agents in this round may share the same parent discipline

For each agent, output a JSON object with these fields:
- name: string starting with "fd-" (e.g., "fd-perfumery-accord")
- focus: one-line description of what this agent reviews
- persona: 1-2 sentences describing the agent's expertise and approach
- decision_lens: 1-2 sentences on how this agent prioritizes findings
- review_areas: array of 4-6 bullet strings, each a specific thing to check
- severity_examples: array of 2-3 objects, each with severity/scenario/condition
- success_hints: array of 1-3 bullet strings, domain-specific success criteria
- task_context: 1-2 sentences of context about the task
- anti_overlap: array of 1-3 strings describing what OTHER agents in this round cover
- source_domain: the real-world knowledge domain (e.g., "physical oceanography")
- distance_rationale: 1 sentence — why is this distant from ALL prior coverage?
- expected_isomorphisms: 1-2 sentences — what specific structural parallels do you expect?

Design rules:
- Agent names: fd-{domain-noun}-{concern} (e.g., fd-tidal-resonance, fd-monastic-scriptoria)
- severity_examples must be concrete and domain-specific
- expected_isomorphisms must name specific mechanisms, not vague analogies ("X maps to Y
  because both involve Z" — name the Z)
- anti_overlap entries should reference other agents in THIS round by name
- distance_rationale must explain distance from the NEAREST already-covered domain

Return ONLY a valid JSON array of objects. No markdown, no explanation.
```

Parse JSON response. On failure, report which round failed and continue to synthesis with agents generated so far.

**Save specs** to `{PROJECT_ROOT}/.claude/flux-gen-specs/{slug}-round-{R}.json`.

**Generate agents** (same as Round 1).

Append new agents to `accumulated_agents` with their `source_domain`.

Display per-round results:
```
Round {R} complete: {N} agents from distant domains
  - fd-{name1}: {focus} [source: {source_domain}]
  - fd-{name2}: {focus} [source: {source_domain}]
  ...
```

---

## Step 4: Synthesize

Display: `📊 Synthesizing cross-domain findings from {len(accumulated)} agents across {rounds} rounds...`

**Read all round spec files** from `{PROJECT_ROOT}/.claude/flux-gen-specs/{slug}-round-*.json` (use Glob to find them, Read to load). These contain the full spec with `expected_isomorphisms`, `source_domain`, and `distance_rationale` — fields not present in the generated `.md` files.

### Step 4a: Choose synthesis path (subagent vs teams)

If `TEAMS_REQUESTED` is `false` (default), proceed to **Step 4b: Subagent synthesis** below.

If `TEAMS_REQUESTED` is `true`, run detection:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/teams_detect.sh
```

- Exit 0 (`available`): proceed to **Step 4c: Teams synthesis**.
- Exit 1, stdout `disabled`: log `--teams requested but CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS not set; falling back to subagent synthesis.`. Set `teams_fallback=detection_disabled`. Proceed to Step 4b.
- Exit 1, stdout `version_too_old`: log `--teams requires claude >= 2.1.32; current version too old. Falling back to subagent synthesis.`. Set `teams_fallback=detection_version`. Proceed to Step 4b.
- Exit 1, stdout `version_unparseable`: log `--teams could not detect claude version; falling back to subagent synthesis.`. Set `teams_fallback=detection_unparseable`. Proceed to Step 4b.

### Step 4b: Subagent synthesis (default path)

Launch a **Sonnet** subagent (Agent tool, `model: sonnet`) with this prompt:

```
You are synthesizing cross-domain structural isomorphisms from a multi-round
semantic space exploration.

Target: {target}

The exploration generated {total} agents across {rounds} rounds, each round
drawing from progressively more distant knowledge domains.

Agent specs from all rounds:
{JSON of all specs from all rounds, including source_domain, expected_isomorphisms, review_areas, focus}

Produce a brainstorm document in markdown with these sections:

## Per-Domain Highlights
For each source_domain, write 2-3 key structural insights and the specific
mechanism that could transfer to the target. Name the agent file
(e.g., `.claude/agents/fd-perfumery-accord.md`) so readers can navigate to
the full spec.

## Cross-Domain Structural Isomorphisms
Patterns that appear independently in 2+ unrelated domains. These are the
highest-value findings — they suggest deep structural truths, not surface
analogies. For each isomorphism:
- Name the 2+ domains that independently suggest it
- Name the specific mechanism in each domain
- Describe the abstract principle they share
- Suggest how it maps to the target

## Novel Mechanism Transfers
Specific, implementable mechanisms from distant domains. Each must include:
- Source domain and agent name
- Mechanism name and how it works in the source domain
- How it maps to the target — which component or module it would modify
- Expected benefit and risk of adoption

Only include mechanisms with a concrete implementation path. No metaphorical
"inspiration" — each transfer must be code-level actionable.

## Open Questions
Domains or angles not yet explored that the synthesis suggests would be
productive for a future exploration round. For each:
- The domain and why it is relevant
- What specific structural insight you expect to find
- Estimated value (high/medium/low)

Write in direct, technical prose. Do not summarize individual agents — synthesize
across them. Find the patterns the individual agents cannot see alone.

Return ONLY the markdown content (no code fences wrapping it).
```

### Step 4c: Teams synthesis (--teams path)

Run the cross-domain debate orchestrator:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/team_synthesize.py \
    --target "{target}" \
    --slug "{slug}" \
    --specs-glob "{PROJECT_ROOT}/.claude/flux-gen-specs/{slug}-round-*.json" \
    --output "{PROJECT_ROOT}/docs/brainstorms/{YYYY-MM-DD}-flux-explore-{slug}.md" \
    --transcript-dir "{PROJECT_ROOT}/docs/research/flux-explore-debates/{slug}" \
    --rounds 2
```

`team_synthesize.py` runs:

1. **Cluster:** `cluster_specs.py` partitions specs into 3 max-distance clusters (or 2 if degraded). Logs centroid distances to stderr regardless of pass/fail.
2. **Pre-flight cost preview:** estimates `teammate_count × per-session × rounds`; if interactive (TTY on stdin), prints preview + 3-second Ctrl-C window. Skipped non-interactively or when `INTERFLUX_TEAMS_PREVIEW_SLEEP=0`.
3. **Spawn-prompt build:** writes the orchestrator-lead's spawn prompt to a temp file and dispatches it to a Claude Code agent-team via the lead. The orchestrator-lead is responsible for spawning 5 teammates (1 author, 3 debaters, 1 questioner) per the prompt.
4. **Debate:** orchestrator runs 2 rounds (blind R1, replies-first R2). `TaskCreated` hook (if installed) caps round count.
5. **Refuse-to-commit detection:** if no mechanism is cited by ≥2 debaters, set `teams_fallback=divergent_clusters` and fall through to subagent synthesis (Step 4b) — the run still produces a usable doc.
6. **Author handoff:** transcript persisted to `docs/research/flux-explore-debates/{slug}/transcript.md`; author receives only the path (Read tool reads from disk; no inline content).
7. **Cost capture:** `cost_capture.sh` enumerates teammate session IDs from the team config, queries `interstat session-cost` per teammate, sums. Transient-empty handling per the F1.3 verdict.

Failure modes:
- Cluster audit returns `divergent_clusters_too_close`: log notice, set `teams_fallback=divergent_clusters`, proceed to Step 4b.
- Spawn API returns error: set `teams_fallback=runtime_failure`, proceed to Step 4b.
- All other errors: set `teams_fallback=runtime_failure`, proceed to Step 4b. Never let a teams failure abort the run.

### Step 4d: Write synthesis output

**Write synthesis** to `{PROJECT_ROOT}/docs/brainstorms/{YYYY-MM-DD}-flux-explore-{slug}.md` with frontmatter:

```yaml
---
artifact_type: brainstorm
bead: {CLAVAIN_BEAD_ID or "none"}
method: flux-explore
target: "{target}"
rounds: {rounds}
total_agents: {total}
date: {YYYY-MM-DD}
# When TEAMS_REQUESTED=true, exactly one of the next two keys is present.
# When TEAMS_REQUESTED=false, neither key is present (byte-identical to legacy frontmatter).
teams_used: true                            # only when teams synthesis succeeded
teams_fallback: detection_disabled          # OR one of: detection_version | detection_unparseable | runtime_failure | divergent_clusters | synthesis_quality_check_fail
synthesis_cost_usd: 0.42                    # teams path only; "incomplete" if any teammate log unflushed
synthesis_quality_check: pass               # teams path only; pass | fail
transcript: docs/research/flux-explore-debates/{slug}/transcript.md  # teams path only, when transcript was written
---
```

`teams_used` and `teams_fallback` are mutually exclusive. The Step 4c-only keys (`synthesis_cost_usd`, `synthesis_quality_check`, `transcript`) are written by `team_synthesize.py` when it owns the synthesis output. When fallback fires, `team_synthesize.py` exits before writing; Step 4b takes over and writes the legacy frontmatter PLUS the `teams_fallback` key (no `teams_used`, no Step-4c-only keys).

Prepend the frontmatter to the synthesis content and write using Write tool.

---

## Step 5: Report

```
Exploration complete: {total} agents across {rounds} rounds.

  Round 1: {names} (domain-appropriate)
  Round 2: {names} ({source_domains})
  Round 3: {names} ({source_domains})

Synthesis: docs/brainstorms/{date}-flux-explore-{slug}.md
Specs: .claude/flux-gen-specs/{slug}-round-{1..N}.json

To activate these agents in a review: /flux-drive <target>
To regenerate a round: /flux-gen --from-specs .claude/flux-gen-specs/{slug}-round-N.json
```

---

## Notes

- Each round checkpoints its specs independently — if the command fails mid-loop, completed rounds are preserved and agents already generated remain on disk
- The synthesis reads from saved JSON specs (not generated .md files) because exploration metadata (source_domain, expected_isomorphisms, distance_rationale) exists only in the specs
- Agents generated by flux-explore are identical to flux-gen agents — they use the same generate-agents.py script and appear in flux-drive triage as Project Agents with +1 category bonus
- The anti-clustering instruction blocks 13 commonly-used AI analogy domains to push the LLM toward genuinely novel territory
- For best synthesis quality, keep total agents ≤ 15 (3 rounds × 5). Higher counts dilute the synthesis
