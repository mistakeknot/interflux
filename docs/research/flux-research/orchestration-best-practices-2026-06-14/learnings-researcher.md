# Learnings Researcher — Multi-Agent Orchestration (Local)

**Question:** Has the interflux project already captured institutional learnings, design notes, or solutions relevant to multi-agent orchestration — concurrency, rate-limits, fan-out/fan-in, dispatch, or synthesis?

**Method:** Local search only — Grep pre-filter across `*.md`, then frontmatter/section reads. No external tools.

### Sources

1. `docs/solutions/` — **PRESENT but thin for this question.** Only 2 files, neither directly about live orchestration concurrency:
   - `docs/solutions/2026-04-13-cross-model-enforce-activation.md:16-23` — cross-model dispatch safety floors, enforce-mode no-op rationale, spec/config drift.
   - `docs/solutions/2026-04-14-fleet-drift-coordination.md:19-23` — atomic counter discipline under concurrent sessions; advisory-wrapper pattern.
2. `docs/spec/core/staging.md:1-310` — Multi-Stage Agent Dispatch (two-stage fan-out, research dispatch, expansion scoring, AgentDropout, conformance).
3. `docs/spec/core/synthesis.md:1-468` — Findings Synthesis (the fan-in algorithm: validation, dedup, convergence, deterministic verdict, partial-failure handling).
4. `docs/spec/contracts/completion-signal.md:1-111` — Agent↔orchestrator state contract: atomic `.partial`→`.md` rename, polling, timeouts, retry policy, error stubs.
5. `docs/spec/extensions/agent-dropout.md:1-39` — Redundancy filter to prune fan-out width.
6. `docs/spec/extensions/cross-model-dispatch.md:1-52` — Model-tier routing, budget pressure, safety floors, model discovery loop.
7. `docs/spec/extensions/budget-system.md:1-45` — Token-budget enforcement as a cost-control gate on dispatch.
8. `skills/flux-engine/phases/launch.md:156-174` — **Canonical concurrency-cap rationale** (MAX_CONCURRENT_AGENTS, Erlang C).
9. `skills/flux-engine/phases/expansion.md:305` — Stage 2 batch-dispatch respecting the cap.
10. `skills/flux-engine/phases/synthesize.md:27` — Quire-mark (run-UUID) guard against concurrent-run contamination.
11. `skills/flux-engine/SKILL.md:124` — Concurrent-run OUTPUT_DIR race caveat + `--output-dir` isolation.
12. `skills/flux-review-engine/phases/track-dispatch.md:187-196` — Nested fan-out cap math (tracks × agents) against shared API limit.
13. `agents/review/references/concurrency-patterns.md:1-586` — Code-pattern library (backoff+jitter, errgroup, TaskGroup, allSettled) — for *reviewed code*, not the engine itself.
14. `docs/brainstorms/2026-04-09-multi-model-activation-brainstorm.md:50` — OpenRouter 20 req/min free-tier limit; open question on internal queue vs slot-cap.

Note: there is no `docs/solutions/performance-issues/`, `.../integration-issues/`, or `patterns/critical-patterns.md` subtree — the canonical solutions store exists but is sparse (2 reflections). The bulk of captured orchestration knowledge lives in `docs/spec/` and inline in `skills/` phase files, not in `docs/solutions/`.

### Findings

**Concurrency cap — why MAX_CONCURRENT_AGENTS=6 (Erlang-C model).** Documented at `launch.md:158,172`: "Anthropic API rate limits and prompt-cache contention degrade throughput when too many agents fan out simultaneously (Erlang C predicts ~30% retry-token waste at the 16-agent fan-out tier)." Default 6 keeps Stage 1 (2-3 agents) unconstrained while staying inside the default-tier per-minute concurrent-session limit. Resolution order: env var → `budget.yaml dispatch.max_concurrent_agents` → 6. Floor of 3-4 preserves Stage 1 parallelism on rate-limited keys (`launch.md:164,174`). The dispatch loop is explicit backpressure: track in-flight tasks, block new dispatch when `in_flight_count >= cap` (`launch.md:166-169`).

**Nested fan-out — preventing multiplicative blow-up.** `track-dispatch.md:189-196`: the API limit is shared across all in-flight subagents, so an outer fan-out (flux-review tracks) multiplies the inner flux-drive cap. Solution: outer `MAX_CONCURRENT_TRACKS=4` + inner `PER_TRACK_AGENT_CAP=3` passed down as the inner `MAX_CONCURRENT_AGENTS`, giving `4×3=12` total — inside default tier limits. Documented guidance to lower `PER_TRACK_AGENT_CAP` to 2 on shared/low-tier keys.

**Two-stage dispatch — variable-cost fan-out (vs single-stage).** `staging.md:13-15`: launching all agents upfront wastes resources; Stage 1 = top 40% by score immediate-parallel, Stage 2 = conditional on findings + user approval. Calibrated across "100+ manual reviews" (adjacency map, `staging.md:76`) and "50+ test reviews" (thresholds, `staging.md:119`). Expansion thresholds ≥3 recommend / 2 offer / ≤1 stop (`staging.md:125-131`).

**Fan-out width reduction — AgentDropout.** `staging.md:165-197` + `agent-dropout.md`: redundancy score (domain convergence 0.4 / adjacency saturation 0.3 / finding density 0.2 / low trust 0.1), drop at ≥0.6. Cites AgentDropout paper (arxiv:2503.18891, 21.6% prompt / 18.4% completion token reduction). Empirically validated 2026-03-26 over 26+ runs / 120+ agent runs: zero P0/P1 recall loss because dropout candidates don't produce P0/P1 findings (`staging.md:197`). Exempt agents (fd-safety, fd-correctness) never dropped.

**Fan-in / synthesis — partial-failure tolerance.** `synthesis.md` is the fan-in design: 4-state output validation (Valid/Error/Malformed/Missing, `synthesis.md:20-26`), index-first collection with lazy prose fallback (`synthesis.md:33-52`), 5 dedup rules, convergence tracking with per-finding M adjustment under content routing and early-stop (`synthesis.md:168-189`), cross-family convergence 1.5× weighting (`synthesis.md:150-162`), deterministic verdict (`synthesis.md:191-205`), graceful degradation on agent failure — "one agent failure shouldn't block the entire synthesis" (`synthesis.md:422`).

**Dispatch↔completion contract — atomic-rename + poll + timeout + retry.** `completion-signal.md`: agents write `.partial`, append sentinel, atomic-rename to `.md`; orchestrator polls every 30s, times out at 5m (local) / 10m (remote), retries once, then writes an error stub so every launched agent has exactly one `.md` (`completion-signal.md:32-80`). Never reads `.partial` for synthesis; never blocks indefinitely.

**Concurrent-run isolation.** Quire-mark run-UUID stamped on every artifact; synthesis skips "Foreign" files from prior/concurrent runs on the same OUTPUT_DIR (`synthesize.md:27`, `launch.md:17`). `--output-dir` forces isolation for genuinely parallel runs on the same target (`SKILL.md:124`).

**Atomic state under concurrency (solutions).** `fleet-drift-coordination.md:19-22`: counter files use tmp+mv atomic discipline — without it "concurrent sessions both read the same counter value and both increment to the same number, effectively halving the sample rate." This is the only `docs/solutions/` entry touching a concurrency race directly.

**Cross-model rate limits / budget pressure.** `cross-model-dispatch.md:12` computes budget pressure and routes tiers; safety floors enforced 4× + pool assertion (`cross-model-enforce-activation.md:16-17`). `budget-system.md` gates dispatch via soft/hard token caps. Open question still un-resolved: OpenRouter free tier 20 req/min — "should the MCP proxy queue internally, or should triage cap non-Claude slots?" (`multi-model-activation-brainstorm.md:50`).

**Reviewed-code concurrency patterns (adjacent, not engine).** `concurrency-patterns.md` holds backoff+jitter, errgroup/TaskGroup fail-fast, `Promise.allSettled`, atomic file replace — guidance fd-correctness applies to *code under review*, useful as a cross-reference for external best-practices but not a description of interflux's own orchestrator.

### Confidence

**High.** The orchestration design space (concurrency cap + rationale, nested fan-out math, staged dispatch, AgentDropout, synthesis fan-in, completion/retry contract, concurrent-run isolation) is explicitly and thoroughly documented in `docs/spec/` and `skills/*/phases/`, with cited empirical calibration and a named queueing-theory model (Erlang C). The specific datapoints asked about (MAX_CONCURRENT_AGENTS=6, Erlang-C, staged vs single-stage) were all located with file:line citations.

### Gaps

- **`docs/solutions/` is sparse for this topic** — only 2 reflections; no performance/integration/patterns subtrees and no `critical-patterns.md`. Orchestration knowledge is captured in spec + phase files instead, so a learnings-only search against `docs/solutions/` alone would under-report.
- **No quantitative Erlang-C derivation captured** — the "~30% retry-token waste at 16-agent tier" figure and the choice of 6 are stated as conclusions, not shown with the underlying model/measurements.
- **OpenRouter rate-limit handling unresolved** — queue-vs-slot-cap is an open brainstorm question (`brainstorm:50`); no documented decision, no documented 429/backoff handling at the engine/dispatch layer (backoff+jitter exists only as advice for reviewed code, not in the dispatch loop, which uses block-on-cap backpressure instead of retry-backoff).
- **No documented adaptive/dynamic concurrency** — the cap is static (env/config/default); no learning from observed throughput or auto-tuning against live rate-limit headers.

<!-- flux-research:complete -->
