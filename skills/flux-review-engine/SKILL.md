---
name: flux-review-engine
description: Invoked from /flux-review — runs multi-track deep review across semantic-distance tiers (adjacent → orthogonal → distant → esoteric), parallel flux-drive dispatch, and cross-track synthesis. Internal engine; users invoke via the slash command.
---

# Flux-Review — Multi-Track Deep Review Engine

Run a fan-out / fan-in review across **multiple semantic-distance tiers**. Each track generates specialized agents at a different distance from the target's domain, runs flux-drive independently, then a synthesis step merges findings — highlighting cross-track convergence as the highest-confidence signal.

## Why Multiple Tracks?

Each tier unlocks qualitatively different insights:
- **Adjacent** agents catch issues requiring deep domain expertise (migration safety, API contracts, concurrency)
- **Orthogonal** agents surface patterns from parallel disciplines at the same abstraction level (broadcast scheduling, supply-chain flow, ATC sequencing)
- **Distant** agents apply structural patterns from unrelated disciplines — mechanisms from pre-modern crafts, physical processes, non-Western knowledge systems
- **Esoteric** agents push to maximally distant domains — patterns separated by centuries, continents, and scales of observation

The garden-salon experiment (22 agents, 3 rounds) showed each additional distance increment produces qualitatively different insights, not just more of the same. For focused code changes, 2 tracks suffices.

## Step 0: Parse Arguments, Load Config, and Triage

### Load configuration

Configuration resolves in priority order (highest wins):
1. Command-line flags (`--quality=max`, `--tracks=3`)
2. Per-project config (`{PROJECT_ROOT}/.claude/flux-review.yaml`)
3. Plugin defaults (`${CLAUDE_PLUGIN_ROOT}/config/flux-review/defaults.yaml`)

Read plugin defaults first, then merge per-project overrides over them (project values win for any key present).

### Parse arguments

Parse `$ARGUMENTS`:
- File path / directory path / inline text-or-topic (required)
- `--tracks=auto|2|3|4` (overrides config `tracks`)
- `--quality=balanced|economy|max` (overrides config `quality`)
- `--creative` (shorthand for `--tracks=4 --quality=max`)
- `--interactive` (restores confirmation gates; default: auto-proceed)

If argument is empty, use AskUserQuestion. If argument is not a valid path on disk, treat as inline text (`INPUT_TYPE = text`).

Set `INTERACTIVE = true` if `--interactive` present, else `false`. Set `QUALITY_MODE`, `TRACK_COUNT`, and `ROUTING` from merged config + flags.

Derive:
```
INPUT_PATH    = <provided path>
PROJECT_ROOT  = <nearest ancestor with .git, or directory of INPUT_PATH>
TARGET_DESC   = <1-line description from reading the file/directory>
SLUG          = <kebab-case from TARGET_DESC, max 40 chars>
DATE          = <YYYY-MM-DD>
```

Read the target (first 200 lines if file, README/CLAUDE.md if directory) to derive TARGET_DESC.

### Per-project configuration

Users may create `{PROJECT_ROOT}/.claude/flux-review.yaml` to override any key from the plugin defaults. Example:
```yaml
quality: max               # this project always uses max quality
tracks: 3                  # default to 3 tracks
agents:
  adjacent: 7              # more domain experts for this project
routing:
  review:
    distant: opus          # upgrade distant reviews to Opus
```

### Track Count Triage (when `--tracks=auto`)

| Signal | Track Count | Reasoning |
|--------|-------------|-----------|
| Focused code change (<100 lines, single file, bugfix) | **2** (adjacent + distant) | Specialist + one cross-domain check |
| Module or feature (~100-500 lines, multiple files) | **3** (+ orthogonal) | Specialist + parallel-discipline + structural |
| Architecture doc, PRD, or design brainstorm | **4** (+ esoteric) | Maximum creative surface |
| Inline text/topic (options analysis, concept exploration) | **4** | Text input implies multi-perspective intent |
| Directory review (entire module/subproject) | **3** | Broad but not full creative exploration |
| `--creative` flag present | **4** | User explicitly wants maximum exploration |

### Track Definitions

| Track | Name | Distance | Agents | When Used |
|-------|------|----------|--------|-----------|
| A | Adjacent | Near | 5 | Always (tracks ≥ 2) |
| B | Orthogonal | Medium | 4 | tracks ≥ 3 |
| C | Distant | Far | 4 (or 5 in 2-track) | tracks ≥ 2 |
| D | Esoteric | Maximum | 3 | tracks = 4 |

Total agents: 2 tracks = 10, 3 tracks = 13, 4 tracks = 16. Track C is always included; B is the middle tier added at 3 tracks; D is the outer frontier added at 4 tracks.

## Step 1: Display Plan and Proceed

Display:
```
Multi-track deep review of: {INPUT_PATH}
Target: {TARGET_DESC}
Tracks: {TRACK_COUNT} (triaged as: {triage_reason})
Quality: {QUALITY_MODE}

{for each active track:}
  Track {letter} ({name}): {agent_count} agents
    Design: {design_model}  Review: {review_model}
Synthesis: {synthesis_model}

Total: up to {total_agents} agents, {TRACK_COUNT} parallel reviews
Estimated context: ~{estimated_tokens}k tokens
```

Token estimates: economy ≈ TRACK_COUNT × 80k, balanced ≈ TRACK_COUNT × 100k, max ≈ TRACK_COUNT × 120k.

**Auto-proceed (default):** Triage is deterministic — proceed directly to Step 2 with the plan displayed for inspection.

**Interactive mode** (`INTERACTIVE = true`): use AskUserQuestion with options "Proceed (Recommended)", "More tracks (+1 track)", "Fewer tracks (just adjacent + distant)", "Cancel".

## Steps 2 + 3: Fan-Out — Generate Agents and Run Reviews

**Read `phases/track-dispatch.md` now.** It contains:
- Step 2 — Fan-Out track agent design (per-track design prompts, common preamble, generate-agents.py invocation)
- Step 3 — Fan-Out flux-drive reviews (per-track dispatch templates, model routing tables for design + review)

## Step 4: Fan-In — Cross-Track Synthesis

**Read `phases/track-synthesis.md` now.** It contains the synthesis subagent prompt template, output frontmatter, and the unified synthesis section structure (Critical Findings, Cross-Track Convergence, Domain-Expert Insights, Parallel-Discipline Insights, Structural Insights, Frontier Patterns, Synthesis Assessment).

## Step 5: Report

```
Multi-track review complete for: {INPUT_PATH}
Tracks: {TRACK_COUNT} ({triage_reason})

{for each active track:}
  Track {letter} ({name}): {N} agents, {findings} findings
Cross-track convergence: {convergent_count} findings appeared in 2+ tracks

Synthesis: docs/research/flux-review/{SLUG}/{DATE}-synthesis.md

Agent specs:
{for each active track:}
  {name}: .claude/flux-gen-specs/{SLUG}-{track_slug}.json

To rerun with existing agents: /flux-drive {INPUT_PATH}
To regenerate a track: /flux-gen --from-specs .claude/flux-gen-specs/{SLUG}-{track_slug}.json
```

## Notes

- All tracks run flux-drive independently and in parallel — they share the same triage/scoring pipeline but operate on different agent pools.
- Cross-track convergence (same issue surfaced from independent reasoning paths at different semantic distances) is the highest-confidence signal — rank by convergence score (N tracks agreeing).
- Track count is triaged from target characteristics but can be overridden (`--tracks=N` or `--creative`).
- Model routing is track-aware by default (`--quality=balanced`): Opus for creative design (C/D), deep reviews (A), and synthesis; Sonnet for routine design (A/B) and lens-application reviews (B/C/D). Override with `--quality=economy` (all Sonnet) or `--quality=max` (all Opus).
- The `--creative` flag is shorthand for `--tracks=4 --quality=max`.
- Distant and esoteric tracks use the same anti-clustering instruction as `/flux-explore` (13 blocked AI-analogy domains).
- Track specs are saved separately per track for independent regeneration.
- If any track fails, the command degrades gracefully to surviving tracks.

### Cost estimates

| Config | Tracks | Quality | Opus tokens | Sonnet tokens | Approx cost |
|--------|--------|---------|-------------|---------------|-------------|
| Quick code review | 2 | economy | 0 | ~200k | ~$0.60 |
| Standard code review | 2 | balanced | ~120k | ~100k | ~$3 |
| Module review | 3 | balanced | ~140k | ~180k | ~$5 |
| Design exploration | 4 | balanced | ~160k | ~240k | ~$7 |
| Full creative | 4 | max | ~400k | 0 | ~$12 |

Cost estimates assume ~100k tokens per track. Actual cost varies with target size and agent count.
