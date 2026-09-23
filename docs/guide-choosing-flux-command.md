# Interflux Command Guide

## Start Here

**If you're reviewing a file, directory, or document:**
```
/flux-drive <path>
```
This is the recommended default. It triages the relevant existing agents, reviews the target, and synthesizes findings without first generating a new multi-track roster.

**If you need a bounded, deeper one-pass review or research pass:**
```
/flux-review <path>
```
Generates domain-expert and cross-domain agents, reviews the target once across 2-4 tracks, and synthesizes convergence. Use it when a careful single pass is not enough but an adaptive loop is not justified.

**If you're brainstorming, not reviewing:**
```
/flux-explore "topic"
```
Mines progressively more distant knowledge domains for structural isomorphisms. No review target — pure creative exploration.

**If you want the deepest possible review — adaptive, goal-seeking, fusing lenses:**
```
/flux-melange <path> --goal="..."
```
The apex of the ladder. Instead of fanning out a fixed set of tracks once and synthesizing, it runs **adaptive rounds** that steer toward the heat (novelty / risk / disagreement) the previous round found, **fuses** high-tension lens pairs into hybrid intersection-detectors, scores findings on **Novelty / Risk / Taste**, and surfaces the spice — not just severity. Reserve it for high-stakes work: architecture pivots, security or data-loss hunts, pre-mortems, and foundational plans. The standard invocation is balanced and three rounds; use to-dry only when the user explicitly asks.

---

## All Commands

| Command | Role | Typical use |
|---------|------|-------------|
| **`/flux-drive`** | **Primary review entry point** — triage + review + synthesize | Reviews by default, including PRs, repeat reviews, and CI pipelines |
| `/flux-review` | Bounded multi-track one-pass review | Careful bounded research; significant artifacts needing fresh semantic-distance lenses |
| `/flux-melange` | **Apex** — goal-seeking adaptive loop, lens fusion, novelty/risk/taste | High-stakes architecture pivots, security/data-loss hunts, pre-mortems, foundational plans |
| `/flux-explore` | Domain exploration without a review target | Brainstorming, architectural inspiration |
| `/flux-research` | Multi-agent research on a question | Answering research questions, not reviewing files |
| `/flux-gen` | Generate agents only (no review) | Building agent libraries, customizing before review |
| `/fetch-findings` | Peek at in-progress findings | While a flux-drive review is still running |

## Choosing an Escalation

Most reviews should stay on `/flux-drive`. Escalate only when the target needs a capability the default pass does not provide.

### Stay on `/flux-drive` when:
- **Routine PRs** — agents already exist from a previous `/flux-review` or `/flux-gen` run. No need to regenerate. (~$1-3 vs ~$3-12)
- **CI/automated pipelines** — flux-drive is the building block that quality-gates and sprint workflows call
- **Reviewing the same codebase repeatedly** — generate agents once with `/flux-review`, then use `/flux-drive` for subsequent passes
- **Cost-sensitive environments** — flux-drive with existing agents is 3-4x cheaper than flux-review

### Use `/flux-explore` instead when:
- **No review target** — you want to explore what tidal dynamics or monastic scriptoria could teach you about your architecture, without reviewing specific code
- **Pure brainstorming** — the goal is a synthesis document about domains and structural isomorphisms, not findings about your files
- **Multi-round progressive distance** — you want 3+ rounds of increasingly distant domains with accumulated context between rounds (flux-review runs all tracks in parallel without inter-track context)

### Use `/flux-melange` instead only when:
- **The work is high-stakes** — an architecture pivot, security or data-loss hunt, pre-mortem, or foundational plan where a missed insight is expensive and the loop should *chase* a scary-but-unconfirmed finding rather than report it once and move on
- **You have a goal, not just a target** — `--goal="find the data-loss path"` steers every round toward that goal; `--weights=risk-hunt` or `--weights=taste` tilts what counts as spice
- **You want lenses that combine, not just stack** — flux-review's lenses only ever *agree* (convergence); melange *fuses* them to surface findings at their intersection that neither parent could see alone
- **Severity is hiding the real risk** — a P2 rare-catastrophe (huge blast radius, low likelihood) leads the melange report but is buried by every other command
- **Use balanced, three rounds by default within melange** — use to-dry only when the user explicitly asks
- **NOT for ordinary discovery, routine PRs, or CI** — use one careful pass, `/flux-drive`, or `/flux-review`

### Use `/flux-gen` instead when:
- **Building an agent library over time** — generate agents across sessions, customize them by hand
- **Agents for a non-flux-drive pipeline** — feeding into a custom review workflow
- **Pre-customization** — you want to edit agent prompts before any review runs

## The Natural Workflow

```
First time reviewing a project:
  /flux-drive <target>               ← default triaged review

Bounded research or deeper one-pass review:
  /flux-review <target>              ← fresh tracks, one pass

Significant architecture change:
  /flux-melange <target> --goal="..." ← balanced, 3 rounds

Brainstorming a new direction:
  /flux-explore "concept"            ← domain exploration, no review target

Routine PR:
  /flux-drive <diff-or-file>         ← core agents + existing project agents
```

## How They Compose

All generated agents land in `.claude/agents/` and are automatically included in future `/flux-drive` triage as Project Agents. This means:

- `/flux-review` generates agents that persist → future `/flux-drive` runs include them for free
- `/flux-explore` generates agents that persist → future `/flux-drive` and `/flux-review` runs include them
- `/flux-gen` generates agents that persist → same

The commands build on each other. Running `/flux-review` once populates your project's agent library; then `/flux-drive` is all you need for routine work.

## Cost Comparison

| Command | Typical cost | When |
|---------|-------------|------|
| `/flux-drive` | ~$1-3 | Routine reviews with existing agents |
| `/flux-review` (2 tracks, balanced) | ~$3 | Standard deep review |
| `/flux-review` (3 tracks, balanced) | ~$5 | Module/feature review |
| `/flux-review` (4 tracks, balanced) | ~$7 | Design docs, PRDs |
| `/flux-review --creative` | ~$12 | Maximum exploration + review |
| `/flux-melange` (3 rounds, balanced) | ~$5 | Standard high-stakes adaptive review |
| `/flux-melange` (to-dry, max) | ~$15 | Explicit user request only; loops until DRY/BUDGET/CEILING (30-slot cap) |
| `/flux-explore` (3 rounds) | ~$0.50 | Brainstorming (no review step) |
| `/flux-gen` | ~$0.10 | Agent generation only |
| `/flux-research` | ~$1-2 | Research questions |

## FAQ

**Q: Which command for a code review?**
A: `/flux-drive path` by default. Use `/flux-review path` for a bounded deeper one-pass review that needs freshly generated semantic-distance lenses.

**Q: Which command for a PR?**
A: `/flux-drive`. PRs are routine — agents already exist, and flux-drive is what the quality-gates pipeline calls.

**Q: Which command for a design brainstorm, gap analysis, or planning research?**
A: Use one careful pass or `/flux-review doc.md --creative` for bounded research. Use `/flux-explore "topic"` for pure domain inspiration with no target. Reserve `/flux-melange <target> --goal="..."` for high-stakes architecture pivots, security/data-loss hunts, pre-mortems, and foundational plans; use to-dry only when explicitly requested.

**Q: Do I ever need to run `/flux-gen` directly?**
A: Rarely. `/flux-review` and `/flux-explore` both call flux-gen internally. Run it directly only if you want agents without any review or synthesis step, or if you want to customize agents before reviewing.

**Q: Can I use agents from one command in another?**
A: Yes. All generated agents persist in `.claude/agents/` and are automatically picked up by flux-drive triage. Agents from `/flux-review`, `/flux-explore`, and `/flux-gen` all interoperate.

**Q: Should I run `/flux-review` in CI?**
A: No. Use `/flux-drive` with `--quality=economy` for CI. flux-review generates new agents every time, which is wasteful for automated pipelines. Generate agents once, then let CI use flux-drive.
