# Content Slicing — Diff and Document Routing

Flux-drive routes content to agents based on relevance. When a diff exceeds 1000 lines or a document exceeds 200 lines, the orchestrator classifies content as **priority** (full) or **context** (summary) per agent. This reduces token cost while preserving full visibility for cross-cutting agents.

This file is the single source of truth for all slicing logic — routing patterns, algorithms, contracts, and reporting.

---

## Routing Patterns

### Cross-Cutting Agents (always full content)

These agents need the complete diff/document regardless of size:

| Agent | Reason |
|-------|--------|
| fd-architecture | Module boundaries, coupling, and design patterns span all files |
| fd-quality | Naming, conventions, and style apply everywhere |

### Domain-Specific Agents

#### fd-safety

**Priority file patterns:**
- `**/auth/**`, `**/authentication/**`, `**/authorization/**`
- `**/deploy/**`, `**/deployment/**`, `**/infra/**`, `**/terraform/**`
- `**/credential*`, `**/secret*`, `**/vault/**`
- `**/migration*`, `**/migrate*`
- `**/.env*`, `**/docker-compose*`, `**/Dockerfile*`
- `**/security/**`, `**/rbac/**`, `**/permissions/**`
- `**/middleware/auth*`, `**/middleware/session*`
- `**/ssl/**`, `**/tls/**`, `**/cert*`
- `**/*-policy*`, `**/iam/**`
- `**/ci/**`, `**/.github/workflows/**`, `**/.gitlab-ci*`

**Priority hunk keywords** (case-insensitive, match within diff hunk lines):
`password`, `secret`, `token`, `api_key`, `apikey`, `api-key`, `credential`, `private_key`, `encrypt`, `decrypt`, `hash`, `salt`, `bearer`, `oauth`, `jwt`, `session`, `cookie`, `csrf`, `cors`, `helmet`, `sanitize`, `escape`, `inject`, `trust`, `allow_origin`, `chmod`, `chown`, `sudo`, `root`, `admin`

#### fd-correctness

**Priority file patterns:**
- `**/migration*`, `**/migrate*`, `**/schema*`
- `**/model*`, `**/models/**`, `**/entity/**`, `**/entities/**`
- `**/db/**`, `**/database/**`, `**/repository/**`, `**/repo/**`
- `**/queue/**`, `**/worker/**`, `**/job/**`, `**/consumer/**`
- `**/sync/**`, `**/lock*`, `**/mutex*`, `**/semaphore*`
- `**/transaction*`, `**/atomic*`
- `**/state/**`, `**/store/**`, `**/reducer*`
- `**/*_test.*`, `**/*_spec.*`, `**/test_*`, `**/spec_*`

**Priority hunk keywords** (case-insensitive):
`transaction`, `commit`, `rollback`, `deadlock`, `mutex`, `lock`, `unlock`, `semaphore`, `atomic`, `race`, `concurrent`, `goroutine`, `channel`, `select`, `async`, `await`, `promise`, `future`, `spawn`, `thread`, `sync.Once`, `sync.Map`, `WaitGroup`, `BEGIN`, `SAVEPOINT`, `CONSTRAINT`, `FOREIGN KEY`, `INDEX`, `ON DELETE`, `ON UPDATE`, `CASCADE`

#### fd-performance

**Priority file patterns:**
- `**/render*`, `**/component*`, `**/view*`, `**/template*`
- `**/query*`, `**/queries/**`, `**/sql/**`
- `**/cache*`, `**/redis*`, `**/memcached*`
- `**/benchmark*`, `**/perf*`, `**/profile*`
- `**/index*`, `**/search*`
- `**/batch*`, `**/bulk*`, `**/stream*`
- `**/loop*`, `**/iterator*`
- `**/webpack*`, `**/vite*`, `**/bundle*`
- `**/image*`, `**/asset*`, `**/static/**`

**Priority hunk keywords** (case-insensitive):
`O(n`, `O(n^2`, `O(log`, `loop`, `for `, `while `, `forEach`, `map(`, `filter(`, `reduce(`, `SELECT`, `JOIN`, `WHERE`, `GROUP BY`, `ORDER BY`, `LIMIT`, `N+1`, `eager`, `lazy`, `prefetch`, `cache`, `memoize`, `useMemo`, `useCallback`, `debounce`, `throttle`, `batch`, `bulk`, `pool`, `connection`, `timeout`, `ttl`, `expir`

#### fd-user-product

**Priority file patterns:**
- `**/cli/**`, `**/cmd/**`, `**/command*`
- `**/ui/**`, `**/tui/**`, `**/view*`, `**/component*`
- `**/template*`, `**/layout*`, `**/page*`
- `**/form*`, `**/input*`, `**/prompt*`
- `**/route*`, `**/router*`, `**/navigation*`
- `**/error*`, `**/message*`, `**/notification*`
- `**/help*`, `**/usage*`, `**/readme*`
- `**/onboard*`, `**/wizard*`, `**/setup*`
- `**/config*` (user-facing configuration)

**Priority hunk keywords** (case-insensitive):
`user`, `prompt`, `flow`, `step`, `wizard`, `onboard`, `error message`, `usage`, `help`, `flag`, `--`, `subcommand`, `menu`, `dialog`, `modal`, `toast`, `alert`, `confirm`, `cancel`, `submit`, `validate`, `placeholder`, `label`, `aria-`, `accessibility`, `a11y`, `i18n`, `locale`

#### fd-game-design

**Priority file patterns:**
- `**/game/**`, `**/games/**`
- `**/simulation/**`, `**/sim/**`
- `**/tick/**`, `**/tick_*`, `**/*_tick.*`
- `**/storyteller/**`, `**/drama/**`, `**/narrative/**`
- `**/needs/**`, `**/mood/**`, `**/desire*`
- `**/ecs/**`, `**/entity/**`, `**/component/**`, `**/system/**`
- `**/balance/**`, `**/tuning/**`, `**/config/balance*`
- `**/ai/**`, `**/behavior/**`, `**/behaviour/**`, `**/utility_ai*`
- `**/procedural/**`, `**/procgen/**`, `**/worldgen/**`
- `**/combat/**`, `**/inventory/**`, `**/crafting/**`

**Priority hunk keywords** (case-insensitive):
`tick`, `tick_rate`, `delta_time`, `fixed_update`, `simulation`, `storyteller`, `drama`, `tension`, `pacing`, `cooldown`, `spawn_rate`, `difficulty`, `balance`, `tuning`, `weight`, `score`, `utility`, `need`, `mood`, `satisfaction`, `decay`, `threshold`, `feedback_loop`, `death_spiral`, `rubber_band`, `catch_up`, `emergent`, `procedural`, `seed`, `noise`, `perlin`, `wave_function`, `agent_ai`, `behavior_tree`, `state_machine`, `blackboard`, `steering`, `pathfind`, `navmesh`

---

## Overlap Resolution and Thresholds

### Overlap Resolution

A file matching priority patterns for multiple agents is marked as priority for **all** of them. This is expected — a migration file is relevant to both fd-safety (credential handling during migration) and fd-correctness (data integrity).

### 80% Overlap Threshold

If an agent's priority files cover >= 80% of total changed lines in the diff (or priority sections cover >= 80% of total document lines), skip slicing for that agent and send the full content. The overhead of compressed summaries is not worth it when almost everything is priority.

### Safety Override

Any section mentioning auth, credentials, secrets, tokens, or certificates is always `priority` for fd-safety regardless of keyword matching.

---

## Diff Slicing

### When It Activates

`INPUT_TYPE = diff` AND total diff lines >= 1000 (`slicing_eligible: yes` from the Diff Profile).

For diffs under 1000 lines, send the full diff to all agents. No slicing needed.

### Classification Algorithm

When slicing is eligible:

1. **Read** the routing patterns from this file (above)
2. **Classify each changed file** as `priority` or `context` per agent:
   - A file is `priority` for an agent if it matches ANY of the agent's priority file patterns OR any hunk in the file contains ANY of the agent's priority keywords
   - All other files are `context` for that agent
3. **Cross-cutting agents** (fd-architecture, fd-quality): always receive the full diff — skip slicing entirely
4. **Domain-specific agents** (fd-safety, fd-correctness, fd-performance, fd-user-product, fd-game-design): receive priority hunks in full + compressed context summary
5. **80% threshold**: If an agent's priority files cover >= 80% of total changed lines, skip slicing for that agent and send the full diff

### Per-Agent Diff Construction

For each **domain-specific agent** that receives sliced content:

**Priority section** — Include the complete diff hunks for all priority files, preserving the original diff format:
```
diff --git a/path/to/file b/path/to/file
--- a/path/to/file
+++ b/path/to/file
@@ ... @@
[full hunk content]
```

**Context section** — For non-priority files, include a one-line summary per file:
```
[context] path/to/file: +12 -5 (modified)
[context] path/to/other: +0 -0 (renamed from old/path)
[context] path/to/binary: [binary change]
```

### Per-Agent Temp File Construction (Diff)

Per-agent files with priority hunks + context summaries:
```bash
REVIEW_FILE_fd_safety="/tmp/flux-drive-${INPUT_STEM}-fd-safety-${TS}.diff"
```

### Edge Cases

| Case | Handling |
|------|----------|
| Binary files | Listed in context summary: `[binary] path: binary change`. Never priority (no text hunks). |
| Rename-only | Context summary: `[renamed] old → new: +0 -0`. Priority for fd-architecture regardless. |
| Multi-commit diff | Deduplicate: each file appears once with aggregate hunks. |
| No pattern matches | Agent gets only compressed summaries + stats. Still sees all file names. |

---

## Document Slicing

### When It Activates

`INPUT_TYPE = file` AND document exceeds 200 lines.

For documents under 200 lines, skip section slicing entirely — all agents receive the full document. The token savings are negligible and the risk of over-filtering is higher.

### Section Classification

#### Classification Methods

**Method 1: Semantic (Interserve Spark)** — preferred when interserve MCP is available.

1. **Extract sections** — Invoke interserve `extract_sections` tool on the document file. Returns structured JSON with section IDs, headings, and line counts.
2. **Classify per agent** — Invoke interserve `classify_sections` tool. Interserve spark assigns each section to each agent as `priority` or `context` with a confidence score (0.0-1.0).
3. **Cross-cutting agents** (fd-architecture, fd-quality) — always receive the full document. Skip classification for these agents.
4. **Safety override** — Any section mentioning auth, credentials, secrets, tokens, or certificates is always `priority` for fd-safety (enforced in classification prompt).
5. **80% threshold** — If `agent_priority_lines * 100 / total_lines >= 80` (integer arithmetic), skip slicing for that agent — send full document.
6. **Domain mismatch guard** — If no agent receives >10% of total lines as priority, classification likely failed. Fall back to full document for all agents.
7. **Zero priority skip** — If an agent has zero priority sections, do not dispatch that agent at all.

**Method 2: Keyword Matching** — fallback when Interserve spark is unavailable or returns low-confidence (<0.6 average).

1. **Extract sections** — Split document by `## ` headings. Each section = heading + content until next heading.
2. **Classify per agent** — For each selected **domain-specific** agent, classify each section:
   - `priority` — section heading or body matches any of the agent's keywords → include in full
   - `context` — no keyword match → include as 1-line summary only
3. **Cross-cutting agents** (fd-architecture, fd-quality) — always receive the full document. Skip classification for these agents.
4. **Safety override** — Any section mentioning auth, credentials, secrets, tokens, or certificates is always `priority` for fd-safety.
5. **80% threshold** — If an agent's priority sections cover >= 80% of total document lines, skip slicing for that agent (send full document).

**Composition rule:** Try Method 1 first. If `classify_sections` returns `status: "no_classification"` or average confidence < 0.6, fall back to Method 2.

A section is `priority` for an agent under Method 2 if:
- The section heading matches any of the agent's keywords (case-insensitive substring)
- The section body contains any of the agent's keywords (sampled — first 50 lines)

### Section Heading Keywords

Additional keywords matched against heading text only:

| Agent | Heading keywords |
|-------|-----------------|
| fd-safety | security, auth, credential, deploy, rollback, trust, permissions, secrets, certificates |
| fd-correctness | data, transaction, migration, concurrency, async, race, state, consistency, integrity |
| fd-performance | performance, scaling, cache, bottleneck, latency, throughput, memory, rendering, optimization |
| fd-user-product | user, UX, flow, onboarding, CLI, interface, experience, accessibility, error handling |
| fd-game-design | game, simulation, balance, pacing, AI, behavior, procedural, storyteller, feedback loop |

### Per-Agent Temp File Construction (Document)

**Cross-cutting agents** (fd-architecture, fd-quality): Write one shared full-document file:
```bash
REVIEW_FILE="/tmp/flux-drive-${INPUT_STEM}-${TS}.md"
```

**Domain-specific agents**: Write one file per agent containing priority sections in full + context section summaries:
```bash
REVIEW_FILE_fd_safety="/tmp/flux-drive-${INPUT_STEM}-fd-safety-${TS}.md"
REVIEW_FILE_fd_correctness="/tmp/flux-drive-${INPUT_STEM}-fd-correctness-${TS}.md"
```

**Per-agent file structure**:
```markdown
[Document slicing active: {P} priority sections ({L1} lines), {C} context sections ({L2} lines summarized)]

## Priority Sections (full content)

{priority section content — preserve original markdown including headings}

## Context Sections (summaries)

- **{Section Name}**: {1-line summary} ({N} lines)
- **{Section Name}**: {1-line summary} ({N} lines)

> If you need full content for a context section, note it as
> "Request full section: {name}" in your findings.
```

### Pyramid Summary (>= 500 lines)

For documents >= 500 lines, generate a Pyramid Summary:
- Write 1-2 sentence summaries per section
- Prepend to each agent's content as a focus guide (even cross-cutting agents benefit from the summary)

For documents 200-500 lines, skip summaries — classify sections only (the savings come from slicing, not from summarization overhead).

### Output: section_map

The section mapping feeds into Phase 2 (Step 2.1c) for per-agent temp file construction:
```
section_map:
  fd-safety: {priority: ["Security", "Deployment"], context: ["Architecture", "Performance"]}
  fd-performance: {priority: ["Performance", "Scaling"], context: ["Security", "Deployment"]}
  fd-architecture: {mode: full}
  fd-quality: {mode: full}
```

---

## Synthesis Contracts

### Agent Content Access

**Diff slicing:**

| Agent Type | Content Received |
|------------|-----------------|
| Cross-cutting (fd-architecture, fd-quality) | Full diff — no slicing |
| Domain-specific (fd-safety, fd-correctness, fd-performance, fd-user-product, fd-game-design) | Priority hunks (full) + context summaries (one-liner per file) |
| Oracle (Cross-AI) | Full diff — external tool, no slicing control |
| Project Agents (.claude/agents/) | Full diff — cannot assume routing awareness |

**Document slicing:**

| Agent Type | Content Received |
|------------|-----------------|
| Cross-cutting (fd-architecture, fd-quality) | Full document — no slicing |
| Domain-specific (fd-safety, fd-correctness, fd-performance, fd-user-product, fd-game-design) | Priority sections (full) + context summaries (one-liner per section) |
| Oracle (Cross-AI) | Full document — external tool, no slicing control |
| Project Agents (.claude/agents/) | Full document — cannot assume routing awareness |

### Slicing Metadata

Each sliced agent prompt includes a metadata line:

**Diff slicing:**
```
[Diff slicing active: P priority files (L1 lines), C context files (L2 lines summarized)]
```

**Document slicing:**
```
[Document slicing active: P priority sections (L1 lines), C context sections (L2 lines summarized)]
```

The orchestrator tracks per-agent access as a mapping for use during synthesis:

**Diff:**
```
slicing_map:
  fd-safety: {priority: [file1, file2], context: [file3, file4], mode: sliced}
  fd-architecture: {priority: all, context: none, mode: full}
  ...
```

**Document:**
```
section_map:
  fd-safety: {priority: ["Security", "Deployment"], context: ["Architecture", "Performance"], mode: sliced}
  fd-architecture: {mode: full}
```

### Synthesis Rules

These rules apply to **both** diff slicing and document slicing:

- **Convergence adjustment**: When counting how many agents flagged the same issue, do NOT count agents that only received context summaries for the file/section in question. A finding from 2/3 agents that saw the content in full is higher confidence than 2/6 total agents.
- **Out-of-scope findings**: If an agent flags an issue in a file/section it received only as context summary, tag the finding as `[discovered beyond sliced scope]`. This is valuable — it means the agent inferred the issue from the file name/stats or section title alone.
- **Slicing disagreements**: Agents may note "Request full hunks: {filename}" or "Request full section: {name}" in their findings. The orchestrator should track these requests. If 2+ agents request full content for the same item, note it as a routing improvement suggestion in the synthesis report.
- **No penalty for silence**: Do NOT penalize an agent for not flagging issues in files/sections it received only as context summaries. Silence on context items is expected, not a gap.

---

## Slicing Report Template

Include this section in the synthesis report **only** when slicing was active (diff >= 1000 lines or document >= 200 lines).

```markdown
### Slicing Report

| Agent | Mode | Priority Items | Context Items | Lines Reviewed (full) |
|-------|------|---------------|---------------|----------------------|
| fd-architecture | full | all | — | {total_lines} |
| fd-safety | sliced | {P} | {C} | {L1} |
| ... | ... | ... | ... | ... |

**Threshold**: {1000 lines for diff / 200 lines for document} (slicing activated)
**Slicing disagreements**: [List any context items that 2+ agents requested full content for, or "None"]
**Routing improvements**: [Suggest pattern additions if agents consistently needed context items, or "None suggested"]
**Out-of-scope discoveries**: [List findings tagged `[discovered beyond sliced scope]`, or "None"]
```

---

## Extending Routing Patterns

**To add patterns for an existing agent:**
Add glob patterns to the agent's "Priority file patterns" list or keywords to the "Priority hunk keywords" list.

**To add a new domain-specific agent:**
Create a new `#### agent-name` section under "Domain-Specific Agents" with:
1. Priority file patterns (glob syntax)
2. Priority hunk keywords (comma-separated, case-insensitive)

**To make an agent cross-cutting:**
Add it to the "Cross-Cutting Agents" table. It will always receive the full content.

**Pattern syntax:**
- File patterns use glob syntax: `*` matches within a directory, `**` matches across directories
- Keywords are matched case-insensitively as substrings within diff hunk lines (the `+` and `-` lines)
- A file is priority if it matches ANY file pattern OR any hunk in the file contains ANY keyword
