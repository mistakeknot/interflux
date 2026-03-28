# Choosing the Right Flux Command

interflux has six commands. Three of them generate and run review agents — `/flux-gen`, `/flux-explore`, and `/flux-review` — and it's not obvious which to use when. This guide explains the differences and when to reach for each.

## Quick Reference

| Command | What it does | When to use it | Output |
|---------|-------------|----------------|--------|
| `/flux-gen` | Generate review agents for a task | You want agents but will run the review yourself | Agent .md files + saved specs |
| `/flux-drive` | Run a review with existing agents | You already have agents (core + generated) | Findings + synthesis |
| `/flux-research` | Multi-agent research on a question | You have a question, not a file to review | Research report |
| `/flux-explore` | Multi-round semantic space exploration | You want agents from progressively distant domains | Agents + cross-domain synthesis doc |
| `/flux-review` | Full pipeline: generate + review + synthesize | You want the complete review experience | Agents + findings + cross-track synthesis |
| `/fetch-findings` | Inspect in-progress review findings | A flux-drive review is running and you want to peek | Raw findings |

## The Three Agent-Generation Commands

### `/flux-gen` — Generate agents only

**What:** Designs 3-5 task-specific review agents via LLM and writes them to `.claude/agents/`.

**When:**
- You want to generate agents once and reuse them across many reviews
- You're building up a project-specific agent library over time
- You want to customize the generated agents before running a review
- You're feeding agents to a different pipeline (not flux-drive)

**What it does NOT do:** Run flux-drive. You get agents, not findings. Run `/flux-drive` separately after.

**Example:**
```
/flux-gen "Review of the authentication module's session handling"
# → generates fd-session-lifecycle, fd-token-rotation, fd-csrf-protection, etc.
# → then manually: /flux-drive src/auth/
```

### `/flux-explore` — Multi-round exploration with synthesis

**What:** Runs flux-gen N times in a loop, each round drawing from progressively more distant knowledge domains. Produces a cross-domain synthesis document identifying structural isomorphisms.

**When:**
- You want to mine distant fields for architectural inspiration
- You're brainstorming, not reviewing — the goal is novel ideas, not bug-finding
- You want to build a diverse agent library for future reviews
- You're doing design exploration for a new system or major pivot

**What it does NOT do:** Run flux-drive. You get agents + a synthesis document, but no review findings against a specific target. The synthesis is about the *domains themselves*, not about your code.

**Key difference from flux-review:** Explore is about **breadth of domains** (how many different fields can we draw from?). Review is about **depth of analysis** (how thoroughly can we review a specific target?).

**Example:**
```
/flux-explore "Agent orchestration patterns for multi-model coordination"
# Round 1: standard domain agents (distributed systems, consensus, scheduling)
# Round 2: distant domains (perfumery, tidal dynamics, common law)
# Round 3: maximally distant (monastic scriptoria, indigenous wayfinding)
# → synthesis doc with cross-domain structural isomorphisms
```

### `/flux-review` — Full pipeline: generate + review + synthesize

**What:** Generates agents across 2-4 semantic distance tiers, runs flux-drive with each tier in parallel, then synthesizes findings across all tracks with cross-track convergence analysis.

**When:**
- You want to review a specific file, directory, or document
- You want both domain-expert findings AND cross-domain structural insights
- You want the review to be self-contained (one command, full results)
- You care about **convergence** — the same issue found independently from different angles

**What it does that the others don't:** Runs the full generate→review→synthesize pipeline in one shot. The synthesis identifies **cross-track convergence** (findings that appeared independently from different semantic distances), which is the highest-confidence signal.

**Example:**
```
/flux-review docs/plans/my-migration-plan.md
# → Track A: 5 migration domain experts review the plan
# → Track C: 4 distant-domain agents review the plan
# → Synthesis: convergent findings, domain insights, structural insights

/flux-review src/pipeline/ --creative
# → 4 tracks (adjacent + orthogonal + distant + esoteric), 16 agents
# → Full creative exploration + review in one shot
```

## Decision Flowchart

```
What do you need?

├─ "I need agents for my project"
│   ├─ Standard domain agents → /flux-gen "task description"
│   └─ Agents from distant/creative domains → /flux-explore "topic"
│
├─ "I need to review a specific file/directory"
│   ├─ Quick review with existing agents → /flux-drive path
│   ├─ Deep review with fresh agents → /flux-review path
│   └─ Maximum creative depth → /flux-review path --creative
│
├─ "I need to research a question"
│   └─ /flux-research "question"
│
└─ "I want creative/architectural inspiration"
    ├─ From distant knowledge domains → /flux-explore "topic"
    └─ Applied to a specific target → /flux-review path --creative
```

## Composition Patterns

The commands compose. Common patterns:

**Build once, review many:**
```
/flux-gen "Review of payment processing module"    # generate agents once
/flux-drive src/payments/checkout.py                # review file 1
/flux-drive src/payments/refund.py                  # review file 2
/flux-drive src/payments/webhook.py                 # review file 3
```

**Explore then review:**
```
/flux-explore "Event-driven pipeline architecture"  # explore domains, get synthesis
# Read synthesis, pick the most promising agents
/flux-drive src/pipeline/                           # review with all generated agents
```

**Progressive depth:**
```
/flux-drive docs/plans/my-plan.md                   # quick pass with core agents
# Found issues? Want deeper analysis?
/flux-review docs/plans/my-plan.md --tracks=3       # deep review with generated agents
```

## Cost Comparison

| Command | Typical cost | Tokens | Agents |
|---------|-------------|--------|--------|
| `/flux-gen` | ~$0.10 | ~10k (design only) | 3-5 |
| `/flux-drive` | ~$1-3 | ~80-150k | 4-8 (from existing pool) |
| `/flux-explore` (3 rounds) | ~$0.50 | ~40k (design + synthesis, no review) | 15 |
| `/flux-review` (2 tracks, balanced) | ~$3 | ~200k | 10 + core agents |
| `/flux-review` (4 tracks, max) | ~$12 | ~400k | 16 + core agents |
| `/flux-research` | ~$1-2 | ~60-100k | 3-5 research agents |

## FAQ

**Q: I just want a code review. Which command?**
A: `/flux-drive path`. It uses the core agents (fd-correctness, fd-safety, etc.) plus any project agents you've already generated. No agent generation step needed.

**Q: When should I generate project-specific agents?**
A: When the core agents consistently miss domain-specific issues. Run `/flux-gen` once for your project's domain, then all future `/flux-drive` runs automatically include those agents.

**Q: What's the difference between `/flux-explore` and `/flux-review --creative`?**
A: Explore generates agents from distant domains and synthesizes what those domains *could* teach you — it's about inspiration. Review `--creative` generates agents AND runs them against a specific target — it's about findings. Use explore when brainstorming, review when analyzing.

**Q: Can I use agents from `/flux-explore` in `/flux-drive`?**
A: Yes. All generated agents land in `.claude/agents/` and are automatically included in flux-drive triage as Project Agents. Explore is a superset of flux-gen.

**Q: Should I run `/flux-review` on every PR?**
A: No. Use `/flux-drive` for routine PRs (it's cheaper and faster). Use `/flux-review` for significant changes — new features, architecture decisions, design documents — where the investment in multi-track analysis pays off.
