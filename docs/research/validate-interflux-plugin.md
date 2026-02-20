# Plugin Validation Report: interflux 0.2.14

**Validated**: 2026-02-18
**Location**: `/home/mk/.claude/plugins/cache/interagency-marketplace/interflux/0.2.14/`

---

## Summary

**PASS** -- The interflux plugin is well-structured and comprehensive. 17 agents, 3 commands, 2 skills, and 2 MCP servers are correctly declared, referenced, and internally consistent. One warning-level issue was found (a reference file incorrectly listed as an agent in plugin.json), and several minor items are noted below. No critical or major issues.

| Metric | Value |
|--------|-------|
| Commands | 3 found, 3 valid |
| Agents | 18 declared, 17 valid agents + 1 reference file (warning) |
| Skills | 2 found, 2 valid |
| Hooks | Not present (none declared) |
| MCP Servers | 2 configured (qmd, exa) |
| Critical Issues | 0 |
| Warnings | 3 |
| Minor Notes | 5 |

---

## Critical Issues (0)

None.

---

## Warnings (3)

### W1: Reference file listed as agent in plugin.json

**File**: `.claude-plugin/plugin.json` line 43

The manifest `agents` array includes `./agents/review/references/concurrency-patterns.md`. This file is a code patterns reference document, not an agent definition -- it has no YAML frontmatter with `name`, `description`, `model`, or `color` fields. It begins with `# Concurrency Patterns Reference` and contains Go/Python/TypeScript/Shell code samples.

Claude Code may attempt to load this as a subagent and fail silently, or expose it as a launchable agent that produces no useful output.

**Fix**: Remove `"./agents/review/references/concurrency-patterns.md"` from the `agents` array in plugin.json. The file is correctly referenced by `fd-correctness` and does not need to be registered as an agent.

### W2: Plugin marked as orphaned

**File**: `.orphaned_at` contains timestamp `1771470869269` (2026-02-19)

The plugin cache copy has an `.orphaned_at` marker file, indicating the marketplace considers this version orphaned (likely superseded by a newer version or removed from registry). This is a cache management concern, not a structural issue, but it means this specific cached version may be cleaned up.

**Fix**: Verify the installed version matches what is active. If a newer version exists, update via `/plugin install interflux`. If this is the active version, the orphan marker may be a false positive from a failed publish cycle.

### W3: Missing `color` field on all agent definitions

**File**: All 17 agents in `agents/review/` and `agents/research/`

None of the agent markdown files include a `color` field in their YAML frontmatter. The Claude Code agent schema supports `color` (blue/cyan/green/yellow/magenta/red) for visual differentiation in the agent picker. All agents currently have `name`, `description`, and `model` but no `color`.

**Fix**: This is optional but recommended for user experience. Add `color:` to each agent's frontmatter to help users visually distinguish review agents (e.g., green) from research agents (e.g., cyan) from cognitive agents (e.g., yellow).

---

## Minor Notes (5)

### M1: Description field in `flux-gen` command lacks quotes

**File**: `commands/flux-gen.md` line 3

The `description` field is unquoted (`description: Generate project-specific review agents from detected domain profiles`) while the other two commands use quoted strings. YAML allows this, but consistency is preferred.

### M2: Skill frontmatter uses minimal fields

**File**: `skills/flux-drive/SKILL.md`, `skills/flux-research/SKILL.md`

Both SKILL.md files have only `name` and `description` in their frontmatter. No `allowed-tools` or other optional fields are declared. This is valid -- skills use all available tools by default -- but explicit tool declarations would provide documentation value.

### M3: No LICENSE file

The plugin has `"license": "MIT"` in plugin.json but no LICENSE file in the root. An `.env.example` and `.gitignore` are present, which is good, but a LICENSE file would match the declared license field.

### M4: `.clavain/interspect/interspect.db` shipped in plugin cache

**File**: `.clavain/interspect/interspect.db`

A SQLite database file is included in the cached plugin. This appears to be a development artifact. While it does not affect plugin functionality, it adds unnecessary size to the plugin package.

### M5: `user-invocable` field on commands

**File**: `commands/flux-drive.md`, `commands/flux-research.md`

These two commands include `user-invocable: true` in their frontmatter. This field is not part of the standard Claude Code command schema (`description`, `argument-hint`, `allowed-tools` are the documented fields). Claude Code ignores unknown frontmatter fields, so this is harmless but represents undocumented custom metadata.

---

## Component Validation Details

### plugin.json Manifest

| Field | Status | Notes |
|-------|--------|-------|
| `name` | VALID | "interflux" -- kebab-case, no spaces |
| `version` | VALID | "0.2.14" -- semantic versioning |
| `description` | VALID | Comprehensive, 250 chars |
| `author` | VALID | `{"name": "mistakeknot"}` |
| `license` | VALID | "MIT" |
| `keywords` | VALID | 10 relevant terms |
| `skills` | VALID | 2 paths, both resolve to existing directories with SKILL.md |
| `commands` | VALID | 3 paths, all files exist |
| `agents` | WARNING | 18 paths, 17 are valid agents, 1 is a reference doc (W1) |
| `mcpServers` | VALID | 2 stdio servers with correct schema |
| JSON syntax | VALID | Passes `jq` validation |

### Commands (3/3 valid)

| Command | description | argument-hint | Content |
|---------|-------------|---------------|---------|
| `flux-drive` | Present, quoted | `[path to file or directory]` | References flux-drive skill |
| `flux-research` | Present, quoted | `[research question]` | References flux-research skill |
| `flux-gen` | Present, unquoted | `[optional: domain name...]` | Full generation workflow (206 lines) |

All commands have YAML frontmatter with `---` delimiters, `description` fields, and meaningful markdown content. The `flux-gen` command is notably self-contained with a complete 6-step workflow.

### Agents (17 valid / 1 reference file)

#### Review Agents (12)

| Agent | name | model | description + examples | System prompt |
|-------|------|-------|----------------------|---------------|
| fd-architecture | VALID | sonnet | VALID (2 examples) | Comprehensive (68 lines) |
| fd-safety | VALID | sonnet | VALID (2 examples) | Comprehensive (83 lines) |
| fd-correctness | VALID | sonnet | VALID (2 examples) | Comprehensive (82 lines, persona "Julik") |
| fd-user-product | VALID | sonnet | VALID (2 examples) | Comprehensive (84 lines) |
| fd-quality | VALID | sonnet | VALID (2 examples) | Comprehensive (89 lines) |
| fd-game-design | VALID | sonnet | VALID (2 examples) | Comprehensive (111 lines) |
| fd-performance | VALID | sonnet | VALID (2 examples) | Comprehensive (89 lines) |
| fd-systems | VALID | sonnet | VALID (2 examples) | Comprehensive (123 lines, 12 lenses) |
| fd-decisions | VALID | sonnet | VALID (2 examples) | Comprehensive (123 lines, 12 lenses) |
| fd-people | VALID | sonnet | VALID (2 examples) | Comprehensive (123 lines, 12 lenses) |
| fd-resilience | VALID | sonnet | VALID (2 examples) | Comprehensive (124 lines, 12 lenses) |
| fd-perception | VALID | sonnet | VALID (2 examples) | Comprehensive (124 lines, 12 lenses) |

All review agents have:
- Valid YAML frontmatter with `name`, `description`, `model`
- Description includes `<example>` blocks with `<commentary>` (required for agent selection)
- Model set to `sonnet` (valid)
- Mandatory "First Step" section checking CLAUDE.md/AGENTS.md
- "What NOT to Flag" section with cross-agent deference
- "Decision Lens" or "Focus Rules" section

The 5 cognitive agents (fd-systems, fd-decisions, fd-people, fd-resilience, fd-perception) share a consistent structure with 12 curated lenses from the Interlens framework, MCP enhancement sections, and cognitive severity guidance.

#### Research Agents (5)

| Agent | name | model | description | System prompt |
|-------|------|-------|-------------|---------------|
| framework-docs-researcher | VALID | haiku | VALID | 118 lines, tool selection matrix |
| repo-research-analyst | VALID | haiku | VALID | 136 lines, AST-grep capable |
| git-history-analyzer | VALID | haiku | VALID | 60 lines, git archaeology |
| learnings-researcher | VALID | haiku | VALID | 265 lines, grep-first filtering |
| best-practices-researcher | VALID | haiku | VALID | 138 lines, multi-phase research |

All research agents have:
- Valid YAML frontmatter with `name`, `description`, `model`
- Description includes `<example>` blocks in the agent .md files
- Model set to `haiku` (valid -- appropriate for research tasks)
- Comprehensive workflow documentation

#### Reference File (NOT an agent)

| File | Status | Notes |
|------|--------|-------|
| references/concurrency-patterns.md | NOT AN AGENT | Code patterns reference, no frontmatter. See W1. |

### Skills (2/2 valid)

#### flux-drive

| Item | Status |
|------|--------|
| SKILL.md | VALID -- 459 lines, complete review protocol |
| SKILL-compact.md | VALID -- 214 lines, condensed version |
| .skill-compact-manifest.json | VALID -- SHA-256 hashes for 9 referenced files |
| phases/launch.md | VALID -- 462 lines, launch protocol |
| phases/synthesize.md | VALID -- 459 lines, synthesis protocol |
| phases/slicing.md | VALID -- 382 lines, content routing |
| phases/shared-contracts.md | VALID -- 102 lines, output format contracts |
| phases/cross-ai.md | VALID -- 31 lines, Oracle comparison |
| phases/launch-codex.md | VALID -- 120 lines, Codex dispatch mode |
| references/agent-roster.md | VALID -- 91 lines, agent inventory |
| references/scoring-examples.md | VALID -- 67 lines, 4 worked examples |

The flux-drive skill is exceptionally well-organized with a modular phase structure. The compact manifest provides content integrity hashes for all phase files.

#### flux-research

| Item | Status |
|------|--------|
| SKILL.md | VALID -- 278 lines, research orchestration protocol |

Simpler than flux-drive (single file), but comprehensive with 3 phases (triage, launch, synthesize), query profiling, and agent scoring.

### MCP Servers (2 configured)

| Server | Type | Command | Status |
|--------|------|---------|--------|
| qmd | stdio | `qmd mcp` | VALID -- semantic search for project docs |
| exa | stdio | `npx -y exa-mcp-server` | VALID -- web search with `${EXA_API_KEY}` env var |

Both servers use `type: "stdio"` with correct `command` and `args` fields. The exa server properly uses `${EXA_API_KEY}` environment variable (not hardcoded). The `.env.example` documents this requirement.

### Hooks

No hooks directory or hooks.json present. This is valid -- hooks are optional.

### File Organization

| Check | Status |
|-------|--------|
| README.md | PRESENT -- clear, concise (57 lines) |
| CLAUDE.md | PRESENT -- project-specific instructions |
| AGENTS.md | PRESENT -- comprehensive dev guide (13K) |
| .gitignore | PRESENT |
| .env.example | PRESENT -- documents EXA_API_KEY |
| LICENSE file | ABSENT (M3) |
| tests/ directory | PRESENT -- structural tests + pyproject.toml |
| scripts/ directory | PRESENT -- 5 utility scripts |
| config/ directory | PRESENT -- domain profiles, budget config |
| docs/ directory | PRESENT -- spec, research, roadmap |

### Security Checks

| Check | Status |
|-------|--------|
| Hardcoded credentials | NONE FOUND |
| API keys in code | NONE -- EXA_API_KEY uses env var placeholder |
| MCP server protocols | STDIO (local) -- N/A for HTTPS check |
| Secrets in examples | NONE -- .env.example has empty values |

---

## Positive Findings

1. **Exceptional skill architecture**: The flux-drive skill uses a modular phase system (shared-contracts, launch, synthesize, slicing, cross-ai) that separates concerns cleanly. The compact manifest with SHA-256 hashes enables integrity verification.

2. **Consistent agent design**: All 17 agents follow a uniform structure with mandatory first steps, clear review approaches, "What NOT to Flag" sections for anti-overlap, and decision lenses. The cognitive agents add a curated lens framework from Interlens.

3. **Progressive enhancement pattern**: MCP servers (qmd, exa), knowledge injection, domain detection, and content slicing all degrade gracefully. Every optional feature has explicit fallback behavior documented.

4. **Comprehensive content routing**: The slicing system (`phases/slicing.md`) provides per-agent file pattern routing with cross-cutting agent protection, 80% overlap thresholds, and safety overrides -- reducing token cost while preserving review quality.

5. **Budget-aware dispatch**: The `config/flux-drive/budget.yaml` provides per-input-type token budgets with soft enforcement, slicing multipliers, and interstat integration for historical cost data.

6. **Test suite present**: Structural tests in `tests/structural/` validate agents, commands, skills, slicing, namespace, and domain detection.

7. **Domain detection system**: The `config/flux-drive/domains/index.yaml` defines 11 domain profiles with weighted signal detection (directories, files, frameworks, keywords), each with a corresponding detailed profile in `config/flux-drive/domains/*.md`.

8. **Self-documenting**: The plugin has CLAUDE.md, AGENTS.md, README.md, a full spec in `docs/spec/`, and inline documentation throughout skill files.

---

## Recommendations

1. **[Fix W1]** Remove `./agents/review/references/concurrency-patterns.md` from the `agents` array in plugin.json. This is a reference document, not a launchable agent.

2. **[Fix W2]** Investigate the `.orphaned_at` marker. If this is the active version, the orphan state may cause cache cleanup to remove it unexpectedly.

3. **[Optional]** Add `color` fields to agent frontmatter for visual differentiation (e.g., review=green, research=cyan, cognitive=yellow).

4. **[Optional]** Add a LICENSE file to match the `"license": "MIT"` declaration in plugin.json.

5. **[Optional]** Add `concurrency-patterns.md` to `.gitignore` for the plugin package or move it to a `skills/flux-drive/references/` location where it does not get confused with agents.

---

## Overall Assessment

**PASS** -- The interflux plugin is a sophisticated, well-engineered multi-agent review and research engine. Its modular architecture, progressive enhancement patterns, and comprehensive documentation are exemplary. The single warning-level issue (reference file listed as agent) is cosmetic and does not affect runtime behavior. The plugin is production-ready at version 0.2.14.
