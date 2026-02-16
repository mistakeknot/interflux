# Flux Research: Multi-Agent Research Orchestration for interflux

**Date:** 2026-02-14
**Status:** Brainstorm
**Author:** mistakeknot

---

## Problem Statement

interflux has a sophisticated multi-agent orchestration pipeline for **review** (flux-drive), but **research** in the Clavain ecosystem is entirely unorchestrated. Five research agents live in Clavain as standalone subagents — a user manually picks one, gets one perspective, and has no way to combine insights from multiple agents into a single coherent answer.

Real research questions naturally span multiple agents:

| User Question | Agents That Should Fire |
|---|---|
| "How should we implement caching?" | learnings + best-practices + framework-docs |
| "Why does this module look like this?" | git-history + repo-research |
| "Onboard me to this project" | repo-research + learnings + framework-docs |
| "What's the right pattern for X in Go?" | best-practices + framework-docs |
| "What changed in this area and what does the community say?" | git-history + best-practices |

Today, a user who wants multi-source research must invoke each agent separately and mentally synthesize the results. This is the same problem flux-drive solved for review — and the same solution pattern applies.

---

## Proposal: flux-research

A second orchestrated skill in interflux, parallel to flux-drive, that triages research agents against a query, dispatches them in parallel, and synthesizes a unified answer with source attribution.

```
interflux/
  skills/
    flux-drive/         # existing — multi-agent REVIEW
    flux-research/      # new — multi-agent RESEARCH
      SKILL.md
      phases/
        triage.md       # query profiling + agent scoring
        launch.md       # parallel dispatch
        synthesize.md   # source merging + confidence ranking
  agents/
    review/             # existing — 7 fd-* agents
    research/           # new — 5 research agents (moved from Clavain)
  commands/
    flux-drive.md       # existing
    flux-gen.md         # existing
    flux-research.md    # new — /interflux:flux-research
```

### Invocation

```
/interflux:flux-research "how should we implement caching in this Go project?"
/interflux:flux-research "onboard me to this codebase"
/interflux:flux-research "what's the history of the auth module and current best practices?"
```

---

## Research Agents (Moving from Clavain)

### Current Roster (5 agents)

| Agent | Focus | Tools Used | Internal/External |
|---|---|---|---|
| **learnings-researcher** | Past solutions from docs/solutions/ | Grep, Read | Internal only |
| **best-practices-researcher** | Industry standards, community patterns | Context7, WebSearch, Glob, Read | External |
| **framework-docs-researcher** | Official library/framework docs | Context7, WebSearch, Bash, Read | External |
| **git-history-analyzer** | Code evolution, blame, contributor mapping | Bash (git commands) | Internal only |
| **repo-research-analyst** | Repository structure, conventions, patterns | Read, Glob, Grep, Bash (ast-grep) | Internal only |

### Observations

**Two distinct classes:**
- **Internal agents** (learnings, git-history, repo-research) — read local files only, fast, deterministic
- **External agents** (best-practices, framework-docs) — call Context7/WebSearch, slower, non-deterministic

This mirrors flux-drive's distinction between "cross-cutting" and "domain-specific" agents, and informs how triage and synthesis should handle them differently.

### Potential New Agent: Exa-Powered Web Researcher

The existing external agents use Context7 (library docs) and WebSearch (general search). Neither is great at:
- Semantic code search across GitHub/StackOverflow
- Finding real-world implementation examples
- Company/project research
- Deep multi-pass retrieval for complex queries

**Exa** fills this gap with:
- **Exa Fast**: Sub-500ms semantic search (meaning-based, not keyword)
- **Exa Deep**: Agentic multi-pass search for optimal results
- **Code search**: Real snippets from GitHub, StackOverflow, technical docs
- **Content retrieval**: Clean, parsed text — not raw HTML

**Integration path:** Exa provides an [official MCP server](https://github.com/exa-labs/exa-mcp-server) (`exa-mcp-server`). It could be added to interflux's plugin.json alongside qmd:

```json
{
  "mcpServers": {
    "qmd": { "type": "stdio", "command": "qmd", "args": ["mcp"] },
    "exa": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "exa-mcp-server"],
      "env": { "EXA_API_KEY": "${EXA_API_KEY}" }
    }
  }
}
```

**Option A: Augment existing agents** — Give best-practices-researcher and framework-docs-researcher access to Exa tools alongside Context7/WebSearch. They choose the best tool for each query.

**Option B: Dedicated exa-researcher agent** — A 6th research agent specialized in deep web research. The triage layer decides when external research warrants Exa's deeper capabilities vs. Context7/WebSearch's lighter touch.

**Option C: Exa as shared infrastructure** — All external-facing agents get Exa tools. The orchestrator doesn't care which tool agents use — they're all "external research" and get dispatched based on query analysis.

**Leaning toward: Option A** (simplest, avoids agent proliferation). The triage layer should route based on the *question type*, not the *search tool*. If a question needs framework docs, framework-docs-researcher runs — and it uses Exa or Context7 or WebSearch based on what's available and what the query needs.

---

## Architecture: How flux-research Differs from flux-drive

### Structural Parallels

| Flux-Drive Concept | Flux-Research Equivalent |
|---|---|
| Document/Diff Profile | **Query Profile** — classify the research question |
| Agent Scoring (0-7) | **Agent Relevance Scoring** — reuses domain infrastructure |
| Domain Detection | **Reuse flux-drive's domain detection** — domain shapes what to search for |
| Content Slicing | **Query Decomposition** — optional, for complex multi-part questions |
| Launch + Monitor | Same — parallel Task dispatch |
| Synthesize + Dedup | **Source Merging** — combine perspectives, rank by confidence |
| Knowledge Compounding | **Cache enrichment** — index results into qmd |
| Findings Index | **Research Index** — structured output per agent |

### Why Research IS Domain-Aware (Revised)

The initial assumption was that research is domain-agnostic — agents look outward for general information, so domain doesn't matter. **This is wrong for advanced domains.**

The quality of research depends on knowing *what to look for*, not just *where to look*. A generalist best-practices-researcher searching "how to handle state" will return Redux/Zustand articles. A domain-aware one that knows the project is `game-simulation` will search for ECS patterns, tick-based state management, rollback netcode, and deterministic simulation. Same query, radically different (and better) results.

This matters most for specialized domains like:

| Domain | Generalist Research Finds | Domain-Aware Research Finds |
|---|---|---|
| ml-pipeline | "ML best practices" listicles | Train/test leakage patterns, DVC vs MLflow trade-offs, ONNX export gotchas |
| game-simulation | Generic game dev tutorials | Utility AI vs behavior trees for NPC needs, tick budget allocation, fixed-timestep accumulator patterns |
| embedded-systems | IoT articles | MISRA-C compliance, DMA buffer alignment, interrupt latency budgeting |
| claude-code-plugin | General plugin architecture | Hook exit code conventions, SKILL.md token budgets, frontmatter field requirements |

**The infrastructure already exists.** interflux has 11 domain profiles in `config/flux-drive/domains/`, each with detailed injection criteria. Flux-drive uses these to inject domain-specific review bullets into review agents. Flux-research can reuse the same detection + injection to inject **domain-specific search guidance** into research agents.

#### How Domain Injection Works for Research

For review agents, a domain injection looks like:
> "Check that training data pipelines don't accidentally include PII" (fd-safety, ml-pipeline domain)

For research agents, the equivalent would be **search directives**:
> "Search for current best practices on train/test split isolation and data leakage prevention in [framework]" (best-practices-researcher, ml-pipeline domain)

This means domain profiles need a new section alongside the existing `## Injection Criteria`:

```markdown
## Research Directives

### best-practices-researcher
- Search for [domain-specific pattern 1]
- Search for [domain-specific pattern 2]

### framework-docs-researcher
- Look up [domain-specific framework concern 1]
- Check for [domain-specific API/tool 1]
```

These directives turn generic "best practices for X" queries into targeted, expert-level research.

#### Domain Detection Reuse

Flux-research reuses flux-drive's existing domain detection pipeline verbatim:

1. Check `{PROJECT_ROOT}/.claude/flux-drive.yaml` cache
2. If stale or missing, run `detect-domains.py`
3. Load domain profiles for detected domains
4. Extract research directives (new section) instead of injection criteria

No new detection code needed. No new domain profiles needed (just a new section in existing profiles). The cache is shared — if flux-drive already detected domains, flux-research reads the same cache.

### Key Simplifications (vs flux-drive)

Flux-research reuses domain detection but is still **simpler** than flux-drive in other dimensions. Research agents mostly *complement* each other (different perspectives) rather than *contradict* (conflicting judgments). This means:

1. **No content slicing** — agents each get the full query (research queries are short, unlike 1000-line diffs)
2. **No staged dispatch** — no expansion logic; all relevant agents launch together
3. **No convergence tracking** — sources complement, they don't need N/M agreement
4. **Simpler scoring** — domain boosts the *quality* of results (via search directives) rather than *selecting* agents. Agent selection is query-type-driven, domain shapes what they search for
5. **No section mapping** — agents get the full query
6. **No conflict resolution** — if sources disagree, present both perspectives with attribution (unlike review where conflicts need a verdict)

### What flux-research DOES need

1. **Query profiling** — classify the research question to select agents
2. **Parallel dispatch** — launch agents concurrently
3. **Source merging** — combine results with attribution and confidence
4. **Deduplication** — when multiple agents find the same information
5. **Structured output** — Research Index format for machine consumption
6. **User confirmation** — lightweight approval before dispatch (which agents, estimated cost)

---

## Phase Design

### Phase 1: Triage

**Step 1.0: Domain Detection (Reuse)**

Check for cached domain detection from flux-drive:

```bash
# Same cache, same script, same exit codes as flux-drive Step 1.0.1
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/detect-domains.py {PROJECT_ROOT} --check-stale
```

If domains are detected, load the corresponding domain profile(s) from `config/flux-drive/domains/*.md` and extract the `## Research Directives` section. These directives will be injected into research agent prompts in Phase 2.

If no domains detected or no cache exists — proceed without directives. The generalist agents still work, they just produce less targeted results.

**Step 1.1: Query Profile**

Parse the user's research query to extract:

```
Query Profile:
- Type: [onboarding | how-to | why-is-it | what-changed | best-practice | debug-context | exploratory]
- Keywords: [extracted technical terms]
- Scope: [project-internal | external | mixed]
- Project context: [from CWD — language, framework, build system]
- Project domains: [from Step 1.0 — e.g., "ml-pipeline (0.72), web-api (0.35)" or "none detected"]
- Estimated depth: [quick (<30s) | standard (<2min) | deep (<5min)]
```

**Query type → agent affinity mapping:**

| Query Type | Primary Agents | Secondary |
|---|---|---|
| onboarding | repo-research | learnings, framework-docs |
| how-to | best-practices, framework-docs | learnings |
| why-is-it | git-history, repo-research | learnings |
| what-changed | git-history | repo-research |
| best-practice | best-practices | framework-docs, learnings |
| debug-context | learnings, git-history | repo-research, framework-docs |
| exploratory | repo-research, best-practices | git-history, framework-docs, learnings |

**Step 1.2: Score Agents**

Simpler than flux-drive's 7-component score:

```
Score: skip | secondary | primary

primary:    Agent's specialty directly matches query type + keywords
secondary:  Agent can contribute useful context but isn't the main source
skip:       Agent has nothing to add for this query
```

Selection rules:
- All primary agents launch
- Secondary agents launch if total agent count <= 4 (resource cap)
- Skip agents never launch
- Minimum: 1 agent (fall through to manual selection if triage fails)
- Maximum: 4 agents (hard cap — research has diminishing returns beyond this)

**Step 1.3: User Confirmation**

```
AskUserQuestion:
  question: "Research plan: [agent1] + [agent2]. Estimated: [quick/standard/deep]. Launch?"
  options:
    - label: "Launch"
    - label: "Edit agents"
    - label: "Cancel"
```

### Phase 2: Launch

**Step 2.1: Prepare Query Context**

For each selected agent, construct a prompt that includes:
- The user's original query
- The query profile (type, keywords, scope, domains)
- Project context (language, framework — from CWD analysis)
- For internal agents: relevant file paths to examine
- For external agents: technology/framework names to search
- **Domain research directives** (when domains detected): domain-specific search guidance from `config/flux-drive/domains/*.md` → `## Research Directives` section, injected per-agent just like flux-drive injects review criteria

Example without domain directives:
> "Research best practices for state management in Go."

Example WITH domain directives (game-simulation detected):
> "Research best practices for state management in Go. DOMAIN CONTEXT (game-simulation): Search for ECS vs component patterns for game state, fixed-timestep accumulator patterns, deterministic simulation state rollback, tick-budget allocation strategies for entity updates."

**Step 2.2: Dispatch**

Launch all agents in parallel using Task tool. Each agent writes output to:
```
{PROJECT_ROOT}/docs/research/flux-research/{query-slug}/{agent-name}.md
```

**Step 2.3: Monitor**

Same polling pattern as flux-drive — watch for completion signals. Simpler because there's no staged expansion.

**Timeout budget by depth:**
- quick: 30s per agent
- standard: 2 min per agent
- deep: 5 min per agent

### Phase 3: Synthesize

**Step 3.1: Collect Results**

Read each agent's output file. Extract structured sections if present, or parse prose.

**Step 3.2: Merge and Attribute**

Combine findings into a unified answer with source attribution:

```markdown
## Research Summary

### Answer
[Synthesized answer combining all agent findings]

### Sources

#### From learnings-researcher (internal)
- [Key insight with link to docs/solutions/ file]

#### From best-practices-researcher (external)
- [Best practice with source attribution]
- [Community consensus with links]

#### From framework-docs-researcher (external)
- [Official docs finding with version info]

### Confidence
- High: [findings confirmed by 2+ agents]
- Medium: [single-source findings from authoritative sources]
- Low: [community opinions, may vary]

### Gaps
- [Questions the research couldn't fully answer]
- [Areas where sources disagreed]
```

**Step 3.3: Source Ranking**

When multiple agents find similar information, rank by authority:
1. Internal learnings (project-specific, proven) — highest
2. Official documentation (authoritative)
3. Community best practices (widely adopted)
4. External code examples (illustrative but contextless)

This inverts the typical authority hierarchy because **project-specific knowledge > general knowledge** for engineering decisions.

**Step 3.4: Optional — Enrich qmd Index**

If a research result seems reusable (not one-off), offer to index it into qmd for future retrieval. This creates a virtuous cycle: research → index → faster future research.

---

## Exa Integration Details

### Where Exa Fits

Exa augments the **external-facing research agents** (best-practices-researcher, framework-docs-researcher). It doesn't replace Context7 or WebSearch — it's a third option agents can choose from based on query needs:

| Tool | Best For | Latency |
|---|---|---|
| Context7 | Official library docs, API references | Fast |
| WebSearch | General queries, recent articles, news | Fast |
| Exa Fast | Semantic code search, finding examples by meaning | <500ms |
| Exa Deep | Complex multi-part research, thorough coverage | Slower (agentic) |

### Agent Decision Logic

Research agents would choose tools based on what they need:

```
Need official API docs?           → Context7 first, Exa Fast fallback
Need real-world code examples?    → Exa Fast (semantic code search)
Need community discussions?       → WebSearch
Need thorough multi-source answer → Exa Deep
Need recent news/changes?         → WebSearch (real-time)
```

### Graceful Degradation

Exa requires an API key (`EXA_API_KEY`). If not set:
- Exa MCP server won't start
- Agents fall back to Context7 + WebSearch (current behavior)
- No error, no degraded experience — just fewer search options

This makes Exa a **progressive enhancement**, not a hard dependency.

### Cost Considerations

Exa pricing (per search):
- Exa Fast: low cost, high volume
- Exa Deep: higher cost, for important queries

The triage layer's `estimated depth` field informs whether agents should use Exa Deep (for deep/standard queries) or stick to Exa Fast/Context7 (for quick queries). This prevents runaway API costs on simple lookups.

---

## Migration: Research Agents from Clavain to interflux

### What Moves

```
Clavain/agents/research/*.md  →  interflux/agents/research/*.md
```

All 5 agents move. Clavain keeps shims (same pattern as review agents):

```
# Clavain/agents/research/best-practices-researcher.md (shim)
---
name: best-practices-researcher
description: "..."
---
[Delegates to interflux:best-practices-researcher]
```

### What Changes in Agents

1. **Namespace references**: Any `clavain:` prefixes → `interflux:`
2. **Exa tool access**: best-practices-researcher and framework-docs-researcher gain Exa MCP tools
3. **Output contract**: Agents adopt a Research Index format (lighter than Findings Index)
4. **Integration points**: `Called by: /interflux:flux-research` replaces manual invocation references

### What Stays in Clavain

- Shim agents (thin redirects to interflux agents)
- The `/clavain:strategy` and `/clavain:work` commands that invoke research (they'd call the interflux agents via shims)
- The using-clavain routing tables (updated to point through shims)

### Test Updates

```
# interflux test counts
agents/review/*.md   → 7 (unchanged)
agents/research/*.md → 5 (new)
skills/*/SKILL.md    → 2 (was 1, now flux-drive + flux-research)
commands/*.md        → 3 (was 2, now + flux-research)

# Clavain test counts
agents/research/*.md → 5 (now shims, still counted)
```

---

## Open Questions

### Q1: How granular should Research Directives be?

Each domain profile needs a `## Research Directives` section with per-agent search guidance. Two approaches:

**Option A: Keyword-level directives** — 3-5 targeted search terms per agent per domain. Lightweight, easy to author for all 11 domains, but the agent still has to figure out *how* to use them.

```markdown
### best-practices-researcher
- ECS entity-component-system patterns
- fixed-timestep game loop
- deterministic simulation rollback
```

**Option B: Full search strategy** — Prose guidance that tells the agent what to search for, what to evaluate, and what to prioritize. More effective but 10x more content to write across 11 domains x 5 agents = 55 sections.

```markdown
### best-practices-researcher
Search for entity-component-system (ECS) patterns for game state management.
Prioritize sparse-set ECS implementations over archetype-based for projects
with high entity churn. Compare Bevy ECS, Legion, and specs-rs approaches.
Evaluate whether the project's entity count justifies ECS overhead vs simpler
component bags.
```

**Leaning:** Option A for v1 — keyword directives are easy to author and give agents enough direction to find the right neighborhood. Upgrade to Option B for high-value domains (ml-pipeline, game-simulation) in v2 based on observed research quality.

### Q2: Should flux-research share flux-drive's phase file pattern?

Flux-drive splits its SKILL.md across 6 phase files (1,763 lines total). Flux-research is simpler — probably 300-500 lines total. One SKILL.md might suffice, with phase files only if it grows.

**Leaning:** Start with a single SKILL.md. Extract phases if it exceeds 400 lines.

### Q3: Should there be a unified `/interflux:go` command?

Instead of separate `/interflux:flux-drive` (review) and `/interflux:flux-research` (research) commands, a unified entry point that detects intent:

```
/interflux:go docs/plans/my-plan.md       → flux-drive (review mode)
/interflux:go "how should we cache this?" → flux-research (research mode)
```

**Leaning:** No. Explicit is better than implicit. Users should know whether they're requesting review or research. A unified command adds ambiguity for marginal convenience.

### Q4: Should research agents write to the same output directory as review agents?

Flux-drive writes to `docs/research/flux-drive/{stem}/`. Flux-research could write to `docs/research/flux-research/{query-slug}/`.

**Leaning:** Yes, separate directories. Different output formats, different retention policies.

### Q5: Should flux-research support Codex dispatch (interserve mode)?

Flux-drive has `launch-codex.md` for dispatching review agents via Codex CLI. Research agents could also benefit from Codex dispatch for parallel execution.

**Leaning:** Not in v1. Research agents are lighter-weight than review agents. Codex dispatch adds complexity for marginal benefit. Revisit if research queries become bottlenecked.

### Q6: How should Exa API costs be managed?

Options:
- **Per-query budget**: triage assigns a cost tier (quick=$0.01, standard=$0.05, deep=$0.20)
- **Monthly cap**: track usage in a local file, warn when approaching limit
- **User approval**: show estimated cost in the confirmation step

**Leaning:** Keep it simple. Show "uses external search (Exa)" in the confirmation step. Don't build cost tracking in v1. Exa's pricing is low enough that per-query budgeting is premature optimization.

### Q7: Knowledge compounding for research?

Flux-drive compounds review patterns into `config/flux-drive/knowledge/`. Should flux-research do the same?

Options:
- Compound into qmd (index research results for future semantic retrieval)
- Compound into `config/flux-research/knowledge/` (parallel knowledge store)
- Don't compound (research is ephemeral — the answer is the product)

**Leaning:** Offer optional qmd indexing (Step 3.4). Don't build a parallel knowledge store. Research results are more diverse and context-dependent than review patterns — they compound less naturally.

### Q8: Cross-AI research via Oracle?

Flux-drive's Phase 4 invokes Oracle (GPT-5.2 Pro) for cross-AI perspective. Should flux-research offer the same?

**Leaning:** Not in v1. Oracle is slow (10-30 min) and designed for review disagreement detection. Research benefits more from breadth (multiple search tools) than from cross-AI validation.

---

## Scope & Effort Estimate

### v1 (MVP)

- [ ] Move 5 research agents from Clavain to interflux
- [ ] Create Clavain shims for backwards compatibility
- [ ] Write flux-research SKILL.md (triage, launch, synthesize)
- [ ] Create `/interflux:flux-research` command
- [ ] Add Exa MCP server to plugin.json (optional dependency)
- [ ] Augment best-practices + framework-docs agents with Exa tool awareness
- [ ] Add `## Research Directives` section to all 11 domain profiles
- [ ] Wire flux-research triage to reuse detect-domains.py + domain cache
- [ ] Update interflux CLAUDE.md and test counts
- [ ] Update Clavain routing tables and test counts

### v2 (Follow-ups)

- [ ] qmd indexing of research results
- [ ] Research Index structured output format
- [ ] Query decomposition for complex multi-part questions
- [ ] Codex dispatch support
- [ ] Research-to-review pipeline (flux-research findings feed into flux-drive context)
- [ ] Domain-specific research agent generation via `/flux-gen` (research counterpart to review agent generation)

---

## Decision Summary

| Decision | Choice | Rationale |
|---|---|---|
| Exa integration | Augment existing agents (Option A) | Simplest, avoids agent proliferation |
| Scoring complexity | 3-point (skip/secondary/primary) for agent selection | Agent selection is query-type-driven |
| Domain detection | **Reuse flux-drive's detection + inject research directives** | Domain shapes *what to search for*, not *which agent to use*. Same detect-domains.py, same cache, new `## Research Directives` section in domain profiles |
| Staged dispatch | Not needed | No expansion logic for research |
| Phase file split | Single SKILL.md initially | <500 lines expected |
| Unified command | No — keep `/flux-drive` and `/flux-research` separate | Explicit > implicit |
| Knowledge compounding | Optional qmd indexing | Research compounds less naturally |
| Cross-AI (Oracle) | Not in v1 | Slow, designed for review not research |
| Codex dispatch | Not in v1 | Research agents are lightweight |
| Exa cost management | Show in confirmation step, no tracking | Premature optimization |
