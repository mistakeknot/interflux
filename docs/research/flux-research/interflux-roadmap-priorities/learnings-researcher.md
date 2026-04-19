# Learnings Research — interflux Roadmap Priorities

**Date:** 2026-04-04
**Task:** Surface institutional knowledge for interflux roadmap planning
**Researcher:** learnings-researcher agent

---

### Sources

The following locations were searched:

1. `/home/mk/projects/Sylveste/docs/solutions/` — categorized solution docs (47 files)
2. `/home/mk/.claude/projects/-home-mk-projects-Sylveste/memory/` — auto-memory files (22 files)
3. `/home/mk/projects/Sylveste/interverse/interflux/docs/research/` — interflux research outputs (22+ files)
4. `/home/mk/projects/Sylveste/interverse/interflux/docs/brainstorms/` — design brainstorms (2 files)
5. `/home/mk/projects/Sylveste/interverse/interflux/docs/plans/` — execution plans (2 files)
6. `/home/mk/projects/Sylveste/interverse/interflux/docs/spec/` — protocol spec (8 files)
7. `/home/mk/projects/Sylveste/interverse/interflux/AGENTS.md` and `CLAUDE.md` — current architecture
8. `/home/mk/projects/Sylveste/docs/research/flux-drive/reaction/` — reaction round review (synthesis)
9. `/home/mk/projects/Sylveste/interverse/interflux/campaigns/flux-review-token-efficiency/` — token efficiency campaign
10. `/home/mk/projects/Sylveste/docs/solutions/patterns/critical-patterns.md` — required reading
11. `/home/mk/.claude/projects/-home-mk-projects-Sylveste/memory/handoff_latest.md` — session handoff context

**Files read:** 20+ full reads, 10+ Grep scans

---

### Findings

#### 1. The Plugin Has Diverged Significantly from Its 2026-02-15 PRD

**Provenance:** `interverse/interflux/docs/PRD.md` (v0.2.29, dated 2026-02-15) vs `interverse/interflux/AGENTS.md` (current state)

The PRD documents "2 skills, 3 commands, 12 agents, 2 MCP servers." The current AGENTS.md documents "17 agents, 4 commands, 1 skill (unified flux-drive), 1 MCP server (exa), 2 hooks." Major changes since the PRD:

- `flux-research` was originally a separate skill — it is now deprecated, merged into `flux-drive mode=research`
- `flux-review` command was added as a new primary entry point (not in PRD)
- `flux-explore` command was added for domain exploration (not in PRD)
- `qmd` MCP server was moved to the `interknow` plugin
- 5 new cognitive review agents were added (fd-systems, fd-decisions, fd-people, fd-resilience, fd-perception)
- Reaction round (Phase 2.5) was added as a new protocol phase
- flux-explore and flux-review are now the recommended entry points; flux-drive is for routine/CI use

The roadmap should be built against the current AGENTS.md state, not the PRD. The PRD is outdated.

**Confidence:** High

---

#### 2. The Reaction Round Specification Has 2 P0 Defects and 12 P1 Gaps (Recently Shipped)

**Provenance:** `docs/research/flux-drive/reaction/synthesis.md` (review of Phase 2.5 spec, 2026-04-02)

The reaction round was reviewed by 4 agents (fd-architecture, fd-correctness, fd-quality, fd-safety). 35 unique findings, gate result: FAIL. The spec was described as "not safe to implement as written."

**P0 defects:**
- **RXN-01**: N=0 agent count causes silent false-proceed — when all Phase 2 agents fail, the convergence gate passes silently with zero agents dispatched, indistinguishable from a valid full-convergence skip
- **RXN-02**: Peer-priming double-discounting ambiguity — spec says "discount before computing ratio" but the script already outputs the ratio, creating two incompatible implementations; negative underflow is possible

**Key P1 gaps (directly relevant to roadmap):**
- No completion monitoring contract for reaction agents (no flux-watch equivalent for `.reactions.md`)
- Unsanitized peer findings injected into LLM prompts (`{peer_findings}` — prompt injection from untrusted flux-gen outputs)
- Title normalization awk strips hyphens, causing false-positive overlaps in convergence gate
- Mode-overrides config field is dead code — quality-gates mode never skips reaction round even though config says it should
- No outer timeout bound — 12 agents × 60s = 720s worst case with no circuit-breaker

**From the handoff:** The reaction round was shipped in bead `sylveste-g3b` (closed) but the P0/P1 fixes from this review may still be outstanding.

**Confidence:** High (from detailed synthesis document)

---

#### 3. Synthesis Context Isolation is the Critical Multi-Agent Architecture Pattern

**Provenance:** `docs/solutions/patterns/synthesis-subagent-context-isolation-20260216.md`

When N review agents each produce 3-5K tokens, naive orchestration floods the host context with 30-40K tokens of prose. The three-tier isolation pattern reduces this 60-80x:

- Tier 1: Review agents → write `.md` files to OUTPUT_DIR
- Tier 2: Synthesis subagent → reads files, deduplicates, writes verdicts + synthesis.md
- Tier 3: Host agent → reads ~10-line compact return only

The synthesis doc found that both flux-drive and flux-research originally read ALL agent output files fully, causing context exhaustion. The fix was the intersynth subagent and file-based output contracts. This pattern is now stable.

**Implication for roadmap:** Any new orchestration layers (reaction rounds, new agent types, cross-AI review) must follow this pattern or risk context exhaustion at scale.

**Confidence:** High

---

#### 4. Domain Detection Was Replaced: Python Heuristics → LLM-Based Classification

**Provenance:** `interverse/interflux/docs/brainstorms/2026-02-22-flux-gen-precheck-brainstorm.md`, `interverse/interflux/docs/plans/2026-02-22-flux-gen-precheck.md`

The 712-line `detect-domains.py` used weighted signal scoring (directory names, file extensions, framework refs, keywords). Known problem: generic signals like `models/`, `api/`, `src/`, `*.go` match everything, producing false positives for projects that aren't actually ml-pipeline or web-api.

**Planned replacement** (bead iv-uaf8): Haiku subagent reads README + build files + 2-3 key source files and classifies into the 11 known domains. Deterministic `generate-agents.py` reads cached domains → writes agent files.

**Current state** (from AGENTS.md): "LLM-based classification. Flux-drive Step 1.0.1 classifies the project into domains based on README, build files, and source files read during Step 1.0. No external scripts — the LLM already has the context."

This migration appears complete. The `detect-domains.py` was simplified and is now kept only as a fallback.

**Confidence:** High (confirmed in AGENTS.md)

---

#### 5. Deduplication Rules Were Formalized: 5 Explicit Cases for Synthesis

**Provenance:** `interverse/interflux/docs/plans/2026-02-19-interflux-dedup-rules.md` (bead iv-ykx7)

Before the plan, synthesis handled deduplication but lacked explicit rules for edge cases. The 5 rules codified:

1. Same file:line + same issue → merge, credit all agents, use highest severity
2. Same file:line + different issues → keep separate, tag `co_located: true`
3. Same issue + different locations → keep separate, add `cross_references` to each
4. Conflicting severity → use highest for verdict computation
5. Conflicting recommendations → include both with agent attribution

Schema additions: `co_located` (boolean) and `cross_references` (string array) were added to findings.json.

**Implication:** The reaction round synthesis has similar deduplication needs for reaction findings. The title normalization bugs (RXN-04 — hyphen stripping) suggest these rules haven't been uniformly applied to the reaction phase.

**Confidence:** High

---

#### 6. Token Efficiency Campaign Identified 40-50% Savings in Instruction Files

**Provenance:** `interverse/interflux/campaigns/flux-review-token-efficiency/learnings.md`

Key validated insight: "Inline examples are the biggest token waste — JSON schema blocks, bash code samples, and verbose prompt templates accounted for ~40% of total phase file tokens. Replacing with compact specs preserved all logic while cutting 50-73% per file."

Specific wins:
- `synthesize-review.md`: 4,230 → 1,125 tokens (-73%)
- `slicing.md`: 3,270 → 1,079 tokens (-67%)
- `reaction.md`: ~1,391 → ~417 tokens (-70%)
- Combined (SKILL.md + launch.md + slicing.md + reaction.md + synthesis agent): 21,561 → 10,693 (-50%)

**Dead end documented:** Conditional loading of slicing.md from SKILL.md — behaviorally correct but the conditional loading instruction itself added more text than it saved.

**Pattern:** Phase files loaded unconditionally (SKILL.md, launch.md) deserve the most aggressive compression. Conditionally-loaded files matter less per invocation.

**Confidence:** High (from validated campaign learnings)

---

#### 7. Convergence Gate Has Known Accuracy Limitations

**Provenance:** `docs/research/flux-drive/reaction/synthesis.md` (findings RXN-04, REACT-03)

Two confirmed failure modes in the convergence gate title normalization in `findings-helper.sh`:

- **RXN-04**: awk strips hyphens (`[^a-zA-Z0-9 ]`), causing passive false-positive overlaps ("Off-by-one" and "Off by one" merge as identical)
- **REACT-03**: An agent can introduce minimal semantic variation ("unbounded memory growth" vs "unbounded memory allocation") to avoid detection — passive false-negatives at minimum; active bypass at worst

The proposed improvement is fuzzy string matching (Jaro-Winkler or trigrams at ~0.75 similarity) or moving convergence detection to synthesis (semantic dedup by synthesis agent).

**Implication for roadmap:** Improving convergence detection accuracy (from exact/normalized string match to semantic similarity) is a known gap with a clear direction.

**Confidence:** High

---

#### 8. The flux-review Command Architecture is Multi-Track with Esoteric Lenses

**Provenance:** `interverse/interflux/config/flux-review/guide.md`, `interverse/interflux/docs/guide-choosing-flux-command.md`

`/flux-review` is the primary entry point (not `/flux-drive`). It generates fresh domain-expert and cross-domain agents per review using a multi-track system:

- **Track A (Adjacent)**: Domain specialists for the target's own domain
- **Track B (Orthogonal)**: Adjacent professions ("supply chain logistics for a data pipeline")
- **Track C (Distant)**: Cross-domain analogies from unrelated fields
- **Track D (Esoteric)**: Pre-industrial crafts, non-Western knowledge systems, physical processes

Track count is configurable (2-4). Quality modes: economy, balanced (default), max. Cost range: ~$1-3 (flux-drive) to ~$12 (flux-review --creative with 4 tracks, max quality).

The economics are documented:
- `/flux-drive`: ~$1-3 (routine reviews with existing agents)
- `/flux-review` 2 tracks: ~$3
- `/flux-review` 4 tracks + --creative: ~$12

**Implication:** The roadmap should distinguish between investments that improve flux-review (deep review) vs. flux-drive (routine/CI) — their users and economics are different.

**Confidence:** High

---

#### 9. Intermediate Finding Sharing via peer-findings.jsonl

**Provenance:** `interverse/interflux/AGENTS.md` (current architecture section)

During parallel reviews, agents share high-severity findings via `{OUTPUT_DIR}/peer-findings.jsonl`. Two severity classes:

- **blocking**: contradicts another agent's analysis (MUST acknowledge)
- **notable**: significant finding that may affect others (SHOULD consider)

**Reaction round finding (REACT-01):** `peer-findings.jsonl` is written by agents with no cryptographic signature or write-once enforcement. An agent can back-date or forward-date entries to suppress/promote peer-priming, affecting the convergence gate's go/no-go decision.

**Implication:** The peer-findings integrity mechanism is a known roadmap item. The fix direction is server-issued monotonic timestamps (not agent-provided) or cross-validation against file mtime.

**Confidence:** High

---

#### 10. Plugin Installation Has Documented Failure Modes

**Provenance:** `docs/solutions/integration-issues/graceful-mcp-launcher-external-deps-interflux-20260224.md` (bead iv-zzo4)

Three independent failure modes on new machine install:

1. **Undeclared hooks**: `hooks/` directory existed but `plugin.json` had no `"hooks"` field — hooks silently ignored with no error
2. **qmd binary missing**: `qmd` not on PATH on a fresh machine (installed via bun); required graceful launcher
3. **EXA_API_KEY not set**: exa-mcp-server starts but every tool call fails silently; required pre-flight check

**Current state**: qmd MCP server moved to interknow plugin. exa MCP server remains with graceful launcher. Hooks are declared in plugin.json (fix was applied).

**Critical pattern from critical-patterns.md**: Never reference bare external binaries in MCP server declarations. Always use a launcher script that checks availability with `exit 0` (not `exit 1`) for optional MCP servers.

**Confidence:** High (fix confirmed applied)

---

#### 11. C3 Composer Wires into flux-drive Launch Phase

**Provenance:** `docs/solutions/2026-03-03-c3-composer-dispatch-plan-generator.md`

The Go subcommand `clavain-cli compose --stage=<stage>` generates deterministic JSON dispatch plans. The flux-drive launch phase (Step 2.0.4) consumes the plan.

**Key pattern**: The C3 composer's "Safety Floor Invariant vs. Routing Overrides" conflict — if a routing override excludes a safety-floor agent (fd-safety, fd-correctness), the invariant is silently violated. Resolution: emit `WARNING:safety_floor_excluded:<agent>:<reason>` at exclusion time.

**Implication:** Safety floors are always-on for fd-safety and fd-correctness — these agents cannot be excluded by budget cuts, routing overrides, or AgentDropout. This is a hard constraint for any roadmap work on agent selection or cost optimization.

**Confidence:** High

---

#### 12. flux-research Merged into flux-drive; Original Brainstorm Was a Different Design

**Provenance:** `interverse/interflux/docs/brainstorms/2026-02-14-flux-research-brainstorm.md`, AGENTS.md

The original brainstorm proposed flux-research as a separate skill with:
- 3-point agent scoring (skip/secondary/primary) instead of flux-drive's 7-component formula
- Max 4 agents hard cap
- No staged dispatch
- Source ranking: internal learnings > official docs > community best practices > external code

Key decision from the brainstorm: "Domain shapes what to search for, not which agent to use." Research agents get domain-specific search directives injected, not different agents per domain.

**Current state:** flux-research SKILL.md exists but is marked "DEPRECATED — merged into flux-drive mode=research." The merge consolidated the two orchestration paths.

**Implication for roadmap:** If research mode performance or quality needs improvement, changes must go into the unified flux-drive SKILL.md, not a separate skill file.

**Confidence:** High

---

#### 13. Dual-Mode Architecture: Standalone vs. Integrated

**Provenance:** `interverse/interflux/AGENTS.md` (Dual-Mode topic guide reference)

The AGENTS.md references a `dual-mode.md` topic guide covering "Standalone vs integrated operation, interbase SDK, known constraints." The plugin operates in two modes:

- **Standalone**: Works without interbase SDK (falls back to no-ops)
- **Integrated**: Sources live interbase SDK for ecosystem coordination

Hooks include `interbase-stub.sh` that sources the live SDK or falls back to inline no-ops.

**Implication:** Any roadmap work touching ecosystem coordination (beads, interspect, Ockham policy) must consider the dual-mode constraint — the plugin must degrade gracefully without the SDK.

**Confidence:** Medium (topic guide referenced but not read in full)

---

#### 14. Knowledge Lifecycle is Now Owned by interknow

**Provenance:** `interverse/interflux/AGENTS.md`, `docs/spec/extensions/knowledge-lifecycle.md`

The spec defines knowledge management (provenance, decay, injection) but interflux no longer owns the implementation — it was delegated to the interknow plugin. Key design:

- **Provenance tracking**: `independent` (re-discovered without prompting) vs `primed` (re-confirmed while in context)
- **Temporal decay**: entries not independently confirmed in 10 reviews are archived
- **Injection**: top 5 relevant entries injected via semantic search (qmd, served by interknow)
- **Compounding**: new patterns extracted from review findings and saved via interknow

Local knowledge entries remain in `config/flux-drive/knowledge/` for reference and migration.

**Open bead**: `iv-wz3j` — "[interflux] Role-aware latent memory architecture experiments" — still open. This suggests knowledge/memory architecture is an active area of investigation.

**Confidence:** High

---

#### 15. Sycophancy Calibration is Measured in Reaction Round Synthesis

**Provenance:** `docs/research/flux-drive/reaction/synthesis.md` (Sycophancy Analysis section)

The reaction round synthesis includes a sycophancy analysis measuring per-agent agreement rates across reaction moves. From the actual review:

| Agent | agree rate | missed-this count |
|-------|-----------|-------------------|
| fd-architecture | 67% | 0 |
| fd-correctness | 100% | 0 |
| fd-quality | 67% | 0 |
| fd-safety | 17% | 3 |

**Overall conformity**: 52.75% — described as "healthy diversity, no sycophancy signals."

The Sawyer Flow Envelope metrics (Gini coefficient, novelty rate, response relevance) were used to assess discourse quality. Gini ~0.15 (healthy), novelty 1.0, relevance 1.0.

**Implication:** The sycophancy detection and discourse quality measurement infrastructure is operational. Roadmap items around improving review independence or calibration have working measurement infrastructure to validate against.

**Confidence:** High

---

#### 16. Self-Dispatch Stop Hook Merging Pattern

**Provenance:** `docs/solutions/patterns/2026-03-20-self-dispatch-stop-hook-integration.md`

When adding new actions to the Stop hook (e.g., reaction round dispatch, self-dispatch after completion), they must be merged as tiers inside `auto-stop-actions.sh`, NOT as separate hooks. The shared `stop` sentinel enforces one blocking action per stop cycle.

Key correctness finding: "Only emit `block` after confirmed claim — the most dangerous bug is phantom dispatch, emitting a `block` decision for a bead the agent doesn't own."

**Implication:** If interflux gains stop-hook integration (e.g., auto-recording findings to beads, reaction round triggered from stop hook), the tier pattern must be followed.

**Confidence:** High

---

### Confidence Summary

| Finding | Confidence | Basis |
|---------|-----------|-------|
| 1. PRD vs current state divergence | High | Direct comparison of PRD and AGENTS.md |
| 2. Reaction round P0/P1 defects | High | Detailed synthesis document from 4-agent review |
| 3. Synthesis context isolation pattern | High | Full solution doc read |
| 4. LLM-based domain detection | High | Confirmed in AGENTS.md |
| 5. Deduplication 5-rule formalization | High | Full plan doc read |
| 6. Token efficiency campaign findings | High | Validated campaign learnings |
| 7. Convergence gate accuracy limits | High | From reaction round review |
| 8. flux-review multi-track architecture | High | Full guide doc read |
| 9. peer-findings.jsonl integrity | High | From reaction round review |
| 10. Plugin install failure modes | High | Full solution doc read |
| 11. C3 Composer + safety floors | High | Full solution doc read |
| 12. flux-research merge status | High | AGENTS.md and brainstorm |
| 13. Dual-mode architecture | Medium | Referenced but topic guide not fully read |
| 14. Knowledge lifecycle delegation | High | AGENTS.md + open bead reference |
| 15. Sycophancy measurement | High | Full synthesis doc read |
| 16. Stop hook merging pattern | High | Full solution doc read |

---

### Gaps

1. **Reaction round activation bead (sylveste-g3b)**: The handoff notes it was "closed" but the P0/P1 review findings from `docs/research/flux-drive/reaction/synthesis.md` indicate the spec was FAIL. Whether the fixes were applied before closing is unclear. This is the highest-priority gap to verify.

2. **flux-review command internals**: The guide was read but the actual `commands/flux-review.md` was not. The multi-track agent generation algorithm, how tracks A/B/C/D are designed, and the synthesis protocol for cross-track convergence are not documented here.

3. **flux-explore command**: The command exists and is documented in the guide, but `commands/flux-explore.md` was not read. The progressive domain exploration algorithm details are unknown.

4. **interflux PHILOSOPHY.md**: The interflux PHILOSOPHY.md file was referenced in the vision doc but not read. Project-specific philosophy may contain constraints or directions not captured here.

5. **Role-aware memory experiments (iv-wz3j)**: The open bead references latent memory architecture experiments but no corresponding brainstorm or research doc was found. This may be a future-scoped item with no docs yet.

6. **Cross-AI review via Oracle**: The `cross-ai.md` phase file and Oracle integration are referenced in AGENTS.md but not read. The current status and any known issues with Oracle-based review are unknown.

7. **Budget configuration details**: `config/flux-drive/budget.yaml` and `scripts/estimate-costs.sh` are referenced. The current budget constraints, per-agent defaults, and AgentDropout threshold details were not examined.

8. **Interbase SDK integration depth**: The `dual-mode.md` topic guide was not read. The exact boundary between standalone and integrated operation, and what features degrade without the SDK, is not captured.

<!-- flux-research:complete -->
