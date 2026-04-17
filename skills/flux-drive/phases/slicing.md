# Content Slicing — Diff and Document Routing

Flux-drive routes content to agents based on relevance. Diffs >= 1000 lines and documents >= 200 lines get per-agent slicing: **priority** (full) for relevant content, **context** (summary) for the rest. Cross-cutting agents (fd-architecture, fd-quality) always get full content.

---

## Routing Patterns

### Cross-Cutting Agents (always full content)

| Agent | Reason |
|-------|--------|
| fd-architecture | Module boundaries, coupling, and design patterns span all files |
| fd-quality | Naming, conventions, and style apply everywhere |

### Domain-Specific Agents

#### fd-safety

**Priority file patterns:**
`**/auth/**`, `**/authentication/**`, `**/authorization/**`, `**/deploy/**`, `**/infra/**`, `**/terraform/**`, `**/credential*`, `**/secret*`, `**/vault/**`, `**/migration*`, `**/.env*`, `**/docker-compose*`, `**/Dockerfile*`, `**/security/**`, `**/rbac/**`, `**/permissions/**`, `**/middleware/auth*`, `**/ci/**`, `**/.github/workflows/**`, `**/oauth/**`, `**/sso/**`, `**/keys/**`, `**/webhook*`, `**/token*`, `**/.npmrc`, `**/.pypirc`

**Priority hunk keywords:** `password`, `secret`, `token`, `api_key`, `credential`, `private_key`, `encrypt`, `decrypt`, `hash`, `salt`, `bearer`, `oauth`, `jwt`, `session`, `cookie`, `csrf`, `cors`, `sanitize`, `inject`, `trust`, `chmod`, `sudo`, `admin`

#### fd-correctness

**Priority file patterns:**
`**/migration*`, `**/schema*`, `**/model*`, `**/models/**`, `**/entity/**`, `**/db/**`, `**/database/**`, `**/repository/**`, `**/queue/**`, `**/worker/**`, `**/job/**`, `**/sync/**`, `**/lock*`, `**/mutex*`, `**/transaction*`, `**/atomic*`, `**/state/**`, `**/store/**`, `**/*_test.*`, `**/*_spec.*`

**Priority hunk keywords:** `transaction`, `commit`, `rollback`, `deadlock`, `mutex`, `lock`, `semaphore`, `atomic`, `race`, `concurrent`, `goroutine`, `channel`, `async`, `await`, `promise`, `future`, `spawn`, `thread`, `BEGIN`, `SAVEPOINT`, `CONSTRAINT`, `FOREIGN KEY`, `CASCADE`

#### fd-performance

**Priority file patterns:**
`**/render*`, `**/component*`, `**/query*`, `**/queries/**`, `**/cache*`, `**/redis*`, `**/benchmark*`, `**/index*`, `**/search*`, `**/batch*`, `**/stream*`, `**/loop*`, `**/webpack*`, `**/vite*`, `**/bundle*`, `**/image*`, `**/asset*`

**Priority hunk keywords:** `O(n`, `loop`, `for `, `while `, `forEach`, `map(`, `filter(`, `SELECT`, `JOIN`, `WHERE`, `GROUP BY`, `N+1`, `eager`, `lazy`, `cache`, `memoize`, `useMemo`, `debounce`, `throttle`, `batch`, `pool`, `timeout`, `ttl`

#### fd-user-product

**Priority file patterns:**
`**/cli/**`, `**/cmd/**`, `**/command*`, `**/ui/**`, `**/tui/**`, `**/view*`, `**/component*`, `**/template*`, `**/form*`, `**/input*`, `**/prompt*`, `**/route*`, `**/router*`, `**/error*`, `**/message*`, `**/help*`, `**/onboard*`, `**/config*`

**Priority hunk keywords:** `user`, `prompt`, `flow`, `wizard`, `onboard`, `error message`, `usage`, `help`, `flag`, `--`, `subcommand`, `menu`, `dialog`, `modal`, `toast`, `confirm`, `validate`, `placeholder`, `aria-`, `a11y`, `i18n`

#### fd-game-design

**Priority file patterns:**
`**/game/**`, `**/simulation/**`, `**/tick/**`, `**/storyteller/**`, `**/drama/**`, `**/needs/**`, `**/mood/**`, `**/ecs/**`, `**/balance/**`, `**/tuning/**`, `**/combat/**`, `**/inventory/**`, `**/quest/**`, `**/crafting/**`, `**/npc/**`, `**/ai/**`, `**/terrain/**`, `**/biome/**`, `**/economy/**`

**Priority hunk keywords:** `tick`, `simulation`, `balance`, `spawn`, `cooldown`, `damage`, `health`, `mana`, `score`, `level`, `XP`, `loot`, `drop_rate`, `difficulty`, `pacing`, `tension`, `storyteller`, `drama`, `need`, `mood`, `desire`, `utility`, `satisfaction`

## Thresholds

- **80% overlap**: If priority items cover >= 80% of total lines, send full content (slicing overhead not worth it)
- **Safety override**: Sections mentioning auth/credentials/secrets/tokens/certificates are always priority for fd-safety
- **Multi-agent overlap**: A file matching multiple agents is priority for all of them
- **Zero priority fallback**: Agent with zero priority sections gets full document (log warning, mark as `mode: full (zero-priority fallback)`)

## Diff Slicing

Activates when `INPUT_TYPE = diff` AND total lines >= 1000.

**Algorithm:** Classify each changed file as `priority` or `context` per agent using routing patterns above. Cross-cutting agents get full diff. Domain-specific agents get priority hunks (full diff format) + context summaries (`[context] path: +N -M`). Per-agent temp files: `/tmp/flux-drive-${INPUT_STEM}-${agent}-${TS}.diff`.

**Edge cases:** Binary files → context only. Rename-only → priority for fd-architecture. Multi-commit → deduplicate. No matches → summaries + stats only.

## Document Slicing

Activates when `INPUT_TYPE = file` AND document exceeds 200 lines.

**Method (Keyword, primary):** Split by `## ` headings. Classify per agent using section heading keywords + body keyword sampling (first 50 + last 20 lines). (Historical note: v1 had a semantic `Method 1` via an `interserve MCP classify_sections` tool that returned priority/context with confidence, but the interserve plugin was retired and the MCP tool no longer exists. The keyword method below is now primary.)

**Section heading keywords:**
| Agent | Keywords |
|-------|---------|
| fd-safety | security, auth, credential, deploy, rollback, trust, permissions, secrets, encryption, compliance |
| fd-correctness | data, transaction, migration, concurrency, async, race, state, consistency, validation, schema, queue |
| fd-performance | performance, scaling, cache, bottleneck, latency, memory, rendering, optimization, query, benchmark |
| fd-user-product | user, UX, flow, onboarding, CLI, interface, accessibility, error handling, workflow |
| fd-game-design | game, simulation, balance, pacing, AI, behavior, procedural, storyteller, feedback loop |

**Per-agent files:** Cross-cutting → shared full file. Domain-specific → priority sections (full) + context summaries (`- **Section**: summary (N lines)`). Pyramid summary for docs >= 500 lines; 2-3 sentence abstract for 200-500 lines.

**Output section_map:** `fd-safety: {priority: ["Security", "Deployment"], context: ["Architecture"]}; fd-architecture: {mode: full}`.

---

## Synthesis Contracts

- **Convergence adjustment**: Only count agents that saw content in full when measuring agreement
- **Out-of-scope findings**: Tag as `[discovered beyond sliced scope]` — valuable inference from summaries
- **Slicing requests**: Track "Request full hunks/section" from agents. If 2+ agents request same item, suggest routing improvement
- **No silence penalty**: Don't penalize agents for not flagging issues in context-only items

**Slicing report** (include only when slicing was active):

| Agent | Mode | Priority Items | Context Items | Lines Reviewed |
|-------|------|---------------|---------------|----------------|

Include threshold, disagreements, routing improvements, and out-of-scope discoveries.

## Extending Routing Patterns

- **Add patterns**: Add globs to "Priority file patterns" or keywords to "Priority hunk keywords"
- **New agent**: Add `#### agent-name` section with file patterns + hunk keywords
- **Cross-cutting**: Add to cross-cutting table (always full content)
- Pattern syntax: `*` within directory, `**` across directories. Keywords: case-insensitive substring match in hunk lines
