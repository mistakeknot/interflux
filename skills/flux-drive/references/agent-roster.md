# Agent Roster

Reference roster for flux-drive agent selection. Read this file during Step 1.2 to identify available agents and their invocation details.

---

### Project Agents (.claude/agents/fd-*.md)

Check if `.claude/agents/fd-*.md` files exist in the project root. If so, include them in triage. Use `subagent_type: general-purpose` and include the agent file's full content as the system prompt in the task prompt.

**Note:** `general-purpose` agents have full tool access (Read, Grep, Glob, Write, Bash, etc.) — the same as Plugin Agents. The difference is that Plugin Agents get their system prompt from the plugin automatically, while Project Agents need it pasted into the task prompt.

If no Project Agents exist AND interserve mode is active, flux-drive will bootstrap them via Codex (see `phases/launch-codex.md`). If no Project Agents exist and interserve mode is NOT active, skip this category entirely.

### Plugin Agents (interflux)

These agents are provided by the Clavain plugin. They auto-detect project documentation: when CLAUDE.md/AGENTS.md exist, they provide codebase-aware analysis; otherwise they fall back to general best practices.

| Agent | subagent_type | Domain |
|-------|--------------|--------|
| fd-architecture | interflux:review:fd-architecture | Module boundaries, coupling, patterns, anti-patterns, complexity |
| fd-safety | interflux:review:fd-safety | Threats, credentials, trust boundaries, deploy risk, rollback |
| fd-correctness | interflux:review:fd-correctness | Data consistency, race conditions, transactions, async bugs |
| fd-quality | interflux:review:fd-quality | Naming, conventions, test approach, language-specific idioms |
| fd-user-product | interflux:review:fd-user-product | User flows, UX friction, value prop, scope, missing edge cases |
| fd-performance | interflux:review:fd-performance | Bottlenecks, resource usage, algorithmic complexity, scaling |
| fd-game-design | interflux:review:fd-game-design | Balance, pacing, player psychology, feedback loops, emergent behavior |

### Cognitive Agents (interflux — document review only)

These agents review documents for cognitive blind spots using analytical lenses from the Linsenkasten framework. They are NEVER included for code or diff reviews — the cognitive pre-filter in SKILL.md Step 1.2a gates them to `.md`/`.txt` document inputs only.

| Agent | subagent_type | Domain |
|-------|--------------|--------|
| fd-systems | interflux:review:fd-systems | Feedback loops, emergence, systems dynamics, causal reasoning |
| fd-decisions | interflux:review:fd-decisions | Decision traps, cognitive biases, uncertainty, strategic paradoxes |
| fd-people | interflux:review:fd-people | Trust dynamics, power structures, communication, team culture |
| fd-resilience | interflux:review:fd-resilience | Antifragility, creative constraints, resource dynamics, innovation |
| fd-perception | interflux:review:fd-perception | Mental models, information quality, temporal reasoning, sensemaking |

**Category**: `cognitive` (distinct from `technical` in triage table). When MCP tools from linsenkasten-mcp are available, these agents enhance their review with dynamic lens search.

### Cross-AI (Oracle)

**Availability check**: Oracle is available when:
1. The SessionStart hook reports "oracle: available for cross-AI review", OR
2. `which oracle` succeeds AND `pgrep -f "Xvfb :99"` finds a running process

If neither check passes, skip Cross-AI entirely.

When available, Oracle provides a GPT-5.2 Pro perspective on the same document. It scores like any other agent but gets a +1 diversity bonus (different model family reduces blind spots).

| Agent | Invocation | Domain |
|-------|-----------|--------|
| oracle-council | `oracle --wait -p "<prompt>" -f "<files>"` | Cross-model validation, blind spot detection |

**Important**: Oracle runs via CLI, not Task tool. Use `--write-output` to capture the clean response (stdout redirect loses output in browser mode). Do NOT wrap with `timeout` — Oracle has its own internal timeout that handles session cleanup properly.

```bash
env DISPLAY=:99 CHROME_PATH=/usr/local/bin/google-chrome-wrapper \
  oracle --wait --timeout 1800 \
  --write-output {OUTPUT_DIR}/oracle-council.md.partial \
  -p "Review this {document_type} for {review_goal}. Focus on: issues a Claude-based reviewer might miss. Provide numbered findings with severity." \
  -f "{INPUT_FILE or key files}" && \
  echo '<!-- flux-drive:complete -->' >> {OUTPUT_DIR}/oracle-council.md.partial && \
  mv {OUTPUT_DIR}/oracle-council.md.partial {OUTPUT_DIR}/oracle-council.md || \
  (echo -e "---\nagent: oracle-council\ntier: cross-ai\nissues: []\nimprovements: []\nverdict: error\n---\nOracle failed (exit $?)" > {OUTPUT_DIR}/oracle-council.md)
```

**Why `--write-output` instead of `> file`**: Oracle browser mode writes the GPT response via `console.log` (not raw stdout). When piped to a file, ANSI escape codes contaminate the output and the response can be lost if the process is killed before flush. `--write-output` writes clean assistant text directly to the specified path after the browser scrape completes.

**Why no `timeout` wrapper**: External `timeout` sends SIGTERM, which kills Oracle before it can update session status or write output. Oracle's internal `--timeout` handles cleanup: it marks the session as timed-out, writes partial output, and exits cleanly. Default for gpt-5.2-pro is 60 minutes; we cap at 30 minutes (`1800`).

**Error handling**: If the Oracle command fails or times out, note it in the output file and continue without Phase 4. Do NOT block synthesis on Oracle failures — treat it as "Oracle: no findings" and skip Steps 4.2-4.5.

Oracle counts toward the dynamic slot ceiling. If the roster is already full, Oracle replaces the lowest-scoring Plugin Agent.

### Research Agents (interflux — available for escalation)

Review agents can invoke these for targeted lookups during review. The flux-drive orchestrator can also dispatch them between stages for context enrichment (see Step 2.2a in `phases/launch.md`).

| Agent | subagent_type | Focus |
|-------|--------------|-------|
| best-practices-researcher | interflux:research:best-practices-researcher | Industry standards, community patterns, deprecation checks |
| framework-docs-researcher | interflux:research:framework-docs-researcher | Official library docs, version constraints, API references |
| git-history-analyzer | interflux:research:git-history-analyzer | Code evolution, blame, contributor mapping |
| learnings-researcher | interflux:research:learnings-researcher | Past solutions from docs/solutions/ |
| repo-research-analyst | interflux:research:repo-research-analyst | Repository structure, conventions, patterns |

**Note:** These agents are NOT scored or selected as part of flux-drive triage. They are support agents available on-demand during review, not review agents themselves.
