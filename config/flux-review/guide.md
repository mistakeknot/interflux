# Flux-Review Configuration Guide

How to choose quality mode, track count, and model routing for your project and review targets. This guide is designed for both humans and AI agents configuring `/flux-review`.

## Quick Decision Tree

```
Is this a one-off quick check?
  → /flux-review path --quality=economy

Is this a standard code review (PR, migration, bugfix)?
  → /flux-review path                          (auto: 2 tracks, balanced)

Is this a new feature or module-level change?
  → /flux-review path --tracks=3               (3 tracks, balanced)

Is this a design document, PRD, or architecture decision?
  → /flux-review path --creative               (4 tracks, max quality)

Do you want to set project-wide defaults?
  → Create .claude/flux-review.yaml            (see examples below)
```

## Choosing Quality Mode

### When to use `economy`

- CI integration where you want automated coverage checks
- Reviewing targets you've already reviewed manually (confirmation pass)
- Cost-sensitive environments or high-volume review workflows
- Targets where correctness matters more than creative insight

**What you lose:** Subtle domain-expert findings (adjacent review drops to Sonnet), esoteric agent design collapses to familiar analogies, synthesis produces summaries rather than genuine convergence analysis.

**What you keep:** Full multi-track coverage, all agent types generated, basic finding detection. Economy mode finds obvious issues reliably — it misses the subtle and surprising ones.

### When to use `balanced` (default)

- Day-to-day engineering reviews
- Most PRs and feature work
- Module-level changes where you want both depth and breadth

**What you get:** Opus on the three highest-judgment steps (creative agent design for C/D tracks, deep domain review on A track, cross-track synthesis). Sonnet everywhere else. This captures ~80% of max-quality findings at ~50% of the cost.

**The gap vs. max:** Orthogonal and distant/esoteric *reviews* run on Sonnet. If those agents' prompts are well-written (which flux-gen v5 with severity calibration produces), Sonnet follows them faithfully. The gap is real but narrow — Sonnet occasionally misses a nuanced structural mapping that Opus would catch.

### When to use `max`

- Architecture reviews where a single missed insight costs more than the review
- Design brainstorms and PRDs (the `--creative` flag auto-selects this)
- Establishing a quality baseline for a new project (run max once, then decide if balanced suffices)
- Post-mortem reviews of incidents or production failures
- Any review where you'll act on the findings with high confidence

**What you get over balanced:** Orthogonal and distant track reviews upgrade to Opus. The gain is most visible in cross-track convergence — Opus is better at recognizing when a distant-domain agent and an adjacent-domain agent are flagging the same structural issue from different angles.

## Choosing Track Count

### 2 tracks — Adjacent + Distant

**Total agents:** 10 | **Best for:** Focused code changes

The minimum viable multi-track review. Adjacent agents provide domain expertise; distant agents provide one cross-domain sanity check. Fast, cheap, focused.

**Use when:** The target is well-understood, the change is scoped, and you want confirmation + one outside perspective. Bugfixes, migrations, single-module changes.

**Don't use when:** The target has cross-cutting concerns, involves multiple subsystems, or you suspect the design might be fundamentally wrong (not just incorrectly implemented).

### 3 tracks — Adjacent + Orthogonal + Distant

**Total agents:** 13 | **Best for:** Features, modules, refactors

The orthogonal track adds the "how do other professions solve this?" perspective. A supply chain logistics agent reviewing a data pipeline, or a broadcast engineering agent reviewing an event system, surfaces operational patterns that domain experts take for granted.

**Use when:** The target involves a workflow or process (not just data structures), touches multiple files, or introduces a new pattern to the codebase.

**Don't use when:** The target is a pure algorithm or data structure change (orthogonal track adds noise for math-heavy targets).

### 4 tracks — Adjacent + Orthogonal + Distant + Esoteric

**Total agents:** 16 | **Best for:** Design exploration, brainstorms, architecture

The esoteric track is the frontier. Pre-industrial crafts, non-Western knowledge systems, physical processes at non-human scales. These occasionally produce the single most valuable insight in the entire review — "perfumery accord" → volatility-stratified ensemble architecture, "monastic scriptoria" → stemma-based hallucination tracing.

**Use when:** You're designing something new, exploring alternatives, writing a PRD, or want to be genuinely surprised. The target has enough conceptual surface area for distant analogies to land meaningfully.

**Don't use when:** The target is a focused code change. 16 agents on a 50-line bugfix produces noise. The esoteric track needs conceptual surface area to work against.

## Customizing Model Routing

The routing table in `defaults.yaml` can be overridden per cell. This is useful when you discover that a specific step × track combination consistently under-performs in your project.

### Common customizations

**"My distant-domain reviews keep missing structural mappings"**
```yaml
# .claude/flux-review.yaml
routing:
  review:
    distant: opus    # upgrade from sonnet
```
This happens when the target's domain is complex enough that even lens-application requires deep reasoning. Consider this if distant-track findings are consistently shallow or generic.

**"My adjacent track design is producing overlapping agents"**
```yaml
routing:
  design:
    adjacent: opus   # upgrade from sonnet for better differentiation
agents:
  adjacent: 6        # more agents to cover more subtopics
```
This happens when the target's domain has many non-obvious subspecialties. Opus differentiates better between "migration atomicity" and "schema evolution" than Sonnet does.

**"I want max quality on synthesis but economy everywhere else"**
```yaml
quality: economy
routing:
  synthesis: opus    # override just synthesis
```
This is a valid configuration. The synthesis step reads summaries (~20-40k tokens), so upgrading just this one cell adds modest cost while significantly improving convergence detection.

**"I'm running this in CI and need to minimize cost"**
```yaml
quality: economy
tracks: 2
agents:
  adjacent: 3
  distant: 3
```
6 agents total, all Sonnet. ~$0.40 per review. Catches obvious issues, misses subtle ones. Reasonable for automated gates where a human reviews the output.

## Per-Project Config Examples

### Complex backend service
```yaml
# .claude/flux-review.yaml
quality: balanced
tracks: 3
agents:
  adjacent: 6        # many subsystems: auth, storage, API, queue, etc.
routing:
  review:
    orthogonal: opus  # operational patterns matter in infrastructure
```

### Frontend application
```yaml
quality: balanced
tracks: 2             # UI code benefits less from esoteric analogies
agents:
  adjacent: 5
  distant: 3          # fewer distant agents, accessibility is the main cross-domain win
```

### Research/design project
```yaml
quality: max
tracks: 4
agents:
  esoteric: 5         # maximize frontier exploration
```

### CI integration
```yaml
quality: economy
tracks: 2
agents:
  adjacent: 3
  distant: 2
```

## When to Re-Evaluate Your Config

- After 5+ reviews: check if distant/esoteric tracks are producing actionable findings. If not, drop to fewer tracks.
- After changing project scope: a project that grows from single-module to multi-service may benefit from upgrading tracks 2→3.
- After model releases: new Sonnet versions may close the gap with Opus on creative design, making economy mode more viable.
- If synthesis quality degrades: this usually means too many agents (>16) are diluting the signal. Reduce agent counts before reducing tracks.
