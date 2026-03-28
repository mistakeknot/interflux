# Interflux Command Guide

## Start Here

**If you're reviewing a file, directory, or document:**
```
/flux-review <path>
```
This is the recommended default. It generates domain-expert and cross-domain agents, reviews your target with both, and synthesizes findings with cross-track convergence analysis. It auto-triages track count (2-4) based on target complexity, and model routing is configurable (see `config/flux-review/guide.md`).

**If you're doing a quick routine check (PR, small change):**
```
/flux-drive <path>
```
Uses existing agents only (core + any previously generated project agents). Cheaper and faster. No agent generation step.

**If you're brainstorming, not reviewing:**
```
/flux-explore "topic"
```
Mines progressively more distant knowledge domains for structural isomorphisms. No review target — pure creative exploration.

---

## All Commands

| Command | Role | Typical use |
|---------|------|-------------|
| **`/flux-review`** | **Primary entry point** — generate + review + synthesize | Reviewing anything significant |
| `/flux-drive` | Quick review with existing agents | Routine PRs, repeat reviews, CI pipelines |
| `/flux-explore` | Domain exploration without a review target | Brainstorming, architectural inspiration |
| `/flux-research` | Multi-agent research on a question | Answering research questions, not reviewing files |
| `/flux-gen` | Generate agents only (no review) | Building agent libraries, customizing before review |
| `/fetch-findings` | Peek at in-progress findings | While a flux-drive review is still running |

## When NOT to Use `/flux-review`

Most of the time, `/flux-review` is the right choice. Use the primitives when:

### Use `/flux-drive` instead when:
- **Routine PRs** — agents already exist from a previous `/flux-review` or `/flux-gen` run. No need to regenerate. (~$1-3 vs ~$3-12)
- **CI/automated pipelines** — flux-drive is the building block that quality-gates and sprint workflows call
- **Reviewing the same codebase repeatedly** — generate agents once with `/flux-review`, then use `/flux-drive` for subsequent passes
- **Cost-sensitive environments** — flux-drive with existing agents is 3-4x cheaper than flux-review

### Use `/flux-explore` instead when:
- **No review target** — you want to explore what tidal dynamics or monastic scriptoria could teach you about your architecture, without reviewing specific code
- **Pure brainstorming** — the goal is a synthesis document about domains and structural isomorphisms, not findings about your files
- **Multi-round progressive distance** — you want 3+ rounds of increasingly distant domains with accumulated context between rounds (flux-review runs all tracks in parallel without inter-track context)

### Use `/flux-gen` instead when:
- **Building an agent library over time** — generate agents across sessions, customize them by hand
- **Agents for a non-flux-drive pipeline** — feeding into a custom review workflow
- **Pre-customization** — you want to edit agent prompts before any review runs

## The Natural Workflow

```
First time reviewing a project:
  /flux-review <target>              ← generates agents + deep review

Subsequent reviews in the same project:
  /flux-drive <target>               ← reuses agents, quick + cheap

Significant architecture change:
  /flux-review <target> --creative   ← regenerate with 4 tracks, max quality

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
| `/flux-explore` (3 rounds) | ~$0.50 | Brainstorming (no review step) |
| `/flux-gen` | ~$0.10 | Agent generation only |
| `/flux-research` | ~$1-2 | Research questions |

## FAQ

**Q: Which command for a code review?**
A: `/flux-review path` for the first review of a significant change. `/flux-drive path` for subsequent or routine reviews.

**Q: Which command for a PR?**
A: `/flux-drive`. PRs are routine — agents already exist, and flux-drive is what the quality-gates pipeline calls.

**Q: Which command for a design brainstorm?**
A: `/flux-explore "topic"` if you want domain inspiration without a specific target. `/flux-review doc.md --creative` if you want to review a design document with maximum creative depth.

**Q: Do I ever need to run `/flux-gen` directly?**
A: Rarely. `/flux-review` and `/flux-explore` both call flux-gen internally. Run it directly only if you want agents without any review or synthesis step, or if you want to customize agents before reviewing.

**Q: Can I use agents from one command in another?**
A: Yes. All generated agents persist in `.claude/agents/` and are automatically picked up by flux-drive triage. Agents from `/flux-review`, `/flux-explore`, and `/flux-gen` all interoperate.

**Q: Should I run `/flux-review` in CI?**
A: No. Use `/flux-drive` with `--quality=economy` for CI. flux-review generates new agents every time, which is wasteful for automated pipelines. Generate agents once, then let CI use flux-drive.
