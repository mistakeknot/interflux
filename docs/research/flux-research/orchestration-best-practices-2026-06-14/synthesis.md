---
artifact_type: research-synthesis
method: flux-research
question: "Multi-agent LLM orchestration best practices vs interflux's flux-drive"
query_type: best-practice
agents: [best-practices-researcher, framework-docs-researcher, repo-research-analyst, learnings-researcher]
date: 2026-06-14
---

# Multi-Agent LLM Orchestration: Best Practices vs interflux flux-drive

> Note on method: Exa and Context7 MCP servers were unavailable this session. External
> research (best-practices-researcher, framework-docs-researcher) used the documented
> progressive-enhancement fallback — WebSearch + WebFetch against official docs/primary
> vendor writeups. Internal research (repo-research-analyst, learnings-researcher) used
> local Grep/Read against the interflux repo. Treat external URLs as WebFetch summaries
> rather than byte-for-byte verified pages (see Confidence & Gaps).

## 1. Answer (TL;DR)

The industry consensus for multi-agent LLM orchestration is the **orchestrator-worker
topology**: a lead agent decomposes the task, fans out parallel subagents (each with its
own context and tools), bounds concurrency with a mechanical knob (semaphore /
`max_concurrency` / `num_workers`), merges results through a safe fan-in barrier
(reducers / `collect_events`), retries transient failures with **exponential backoff +
jitter**, persists state for **checkpoint-resume**, and runs a **dedicated synthesis
(and separate citation) step**.

**Verdict: interflux's flux-drive is architecturally aligned with this consensus and in
several dimensions more sophisticated than the reference frameworks** — staged/wave
dispatch matches Anthropic's own design, its delegated-synthesis + dedup/convergence
model is richer than any framework's built-in aggregation, and its filesystem
atomic-rename completion contract gives it partial-failure semantics most SDKs lack.
**Where it diverges, the gap is mechanical enforcement, not design**: flux-drive's
concurrency cap, dispatch loop, and retry race are *LLM-followed prose, not an enforced
semaphore or work-queue*; there is **no 429/exponential-backoff handling at the dispatch
layer** (it relies on block-on-cap backpressure instead); and its central "why 6 agents"
Erlang-C rationale is an **unsourced heuristic** with no in-repo derivation. The
highest-leverage borrowings are a real semaphore (LlamaIndex `num_workers` / LangGraph
`max_concurrency`), exp-backoff+jitter on 429, and checkpoint-resume.

## 2. Best Practices (external)

Consensus practices per subtopic, attributed to the external sources
(best-practices-researcher unless noted; framework-docs-researcher cited as FDR):

- **Fan-out / fan-in.**
  - Orchestrator-worker is the de-facto production topology: lead plans → spawns parallel
    subagents (own context/tools) → synthesizes (Anthropic, "How we built our multi-agent
    research system"). "Workers never talk to each other; every decision lives in the
    orchestrator" (FDR / Anthropic).
  - **Dynamic fan-out** when N is unknown until runtime — LangGraph `Send` is the
    reference (LangChain Academy / machinelearningplus / Markaicode).
  - **Fan-in via a safe-merge barrier** — state reducers (`operator.add`) so concurrent
    writes don't clobber; independent worker-state schema (LangGraph docs).
  - **Scale effort to complexity** — ~1 agent for fact-finding, 2-4 for comparisons, 10+
    for complex research; 3-5 parallel subagents cut research time ~90% vs serial
    (Anthropic).

- **Concurrency & rate-limit control.**
  - **Cap concurrency with a semaphore** (`asyncio.Semaphore(N)`), size N to the RPM
    budget, lower N at high volume to avoid a thundering herd (newline/rednafi practitioner
    guides; Portkey).
  - Distinguish concurrency-limiting (max in-flight) from batching (slice/combine the
    workload); use both together at high volume.
  - Stay ~10-20% under provider limits proactively; **reserve quota for the whole
    workflow before starting** rather than per-call (Portkey, TrueFoundry).
  - **Centralize limiting at a gateway** (Redis/token-bucket) when agents share a key, to
    prevent one agent starving others (Portkey, TrueFoundry).

- **Staged / wave dispatch.**
  - Wave/staged dispatch — lead waits for a wave to finish before deciding the next step —
    is a legitimate, deliberately-chosen tradeoff (simplicity + clean fan-in) rather than a
    deficiency; the cost is head-of-line blocking by the slowest worker. Anthropic's own
    production system dispatches subagents **synchronously in waves** and calls out async
    concurrent dispatch as a future improvement (Anthropic; FDR notes the same caveat).

- **Partial-failure handling & durability.**
  - **Persist plan/state before context limits** so a failed/compacted agent resumes
    rather than restarts (Anthropic).
  - **Checkpoint + resume, don't restart** — durable-execution model (Temporal/Inngest,
    LangGraph checkpointers) replays an event history to resume at the failed step.
  - **Idempotency is a prerequisite** for safe checkpointing/retry of side-effecting tools
    (Temporal/Inngest).
  - **Graceful degradation in fan-in** — synthesize from the subset that succeeded rather
    than aborting the whole run (Anthropic).
  - **Exponential backoff + jitter** on 429s/transient errors; jitter prevents synchronized
    retry storms. Immediate/minimal-backoff retries are an anti-pattern under concurrency.
    Use **per-error-class** policy: transient → retry w/ backoff, permanent → fail fast
    (SparkCo, apxml, TrueFoundry, Portkey).

- **Result synthesis / aggregation.**
  - **Dedicated synthesis step owned by the orchestrator**; subagents return structured,
    condensed findings (often via shared memory, not long chat returns) (Anthropic).
  - **Separate the citation/attribution step** — Anthropic runs a distinct CitationAgent
    after synthesis.
  - **Aggregation strategy per task** — weighted averaging, majority voting, panel/debate;
    LLM-as-judge for ranking ("LLM-as-a-Judge in Multi-Agent Systems"; arXiv 2412.05579).
  - **Preserve disagreement** — retain evidence and surface conflicts, don't flatten into
    fake consensus. Judge is highest-leverage for **termination control** ("are we done?"),
    not just scoring.

## 3. Framework Mechanisms (vocabulary interflux could borrow)

From framework-docs-researcher (named, version-specific primitives):

| Framework | Fan-out | Concurrency cap | Fan-in / merge | Notes |
|---|---|---|---|---|
| **LangGraph** | `Send(node, state)` (dynamic map) | `max_concurrency` (invoke config); `recursion_limit` superstep bound | reducers `Annotated[list, operator.add]` / `add_messages`; `defer=True` barrier node | supersteps = transactional fan-in barriers; per-node `RetryPolicy` exists |
| **LlamaIndex Workflows** | `ctx.send_event(Event(...))` | `@step(num_workers=N)` (default 4) | `ctx.collect_events(ev, [E]*N)` barrier | measured 7.4s→2.6s for workers 1→3; warns shared state needs thread-safety |
| **OpenAI Agents SDK** | `asyncio.gather` (caller-driven; no native primitive) | none native | implicit in manager (agents-as-tools) | handoffs vs `Agent.as_tool()`; successor to Swarm |
| **CrewAI** | `kickoff_for_each_async()`, `async_execution=True` on Task | coarse (crew-level async) | manager (hierarchical) or Python `Flow` | `Process.sequential` / `Process.hierarchical` (needs `manager_llm`/`manager_agent`); `Flow` `@start/@listen/@router` |
| **AG2 (AutoGen fork)** | none (turn-based) | n/a — sequential speaker selection | `GroupChatManager` | `AutoPattern`/`RoundRobin`/`Manual` speaker patterns; **no agent-level parallelism** |
| **MS Agent Framework (MAF)** | typed-edge `Workflow` executors | "supports concurrent execution" | edge-activated executors; checkpointing | **successor to AutoGen** (maintenance mode); `WorkflowBuilder().add_edge().build()` |
| **Anthropic (pattern, not SDK)** | LeadResearcher spawns parallel subagents | synchronous waves (implicit) | lead synthesizes iteratively + CitationAgent | the most directly relevant design reference |

Borrowable vocabulary for interflux: **`max_concurrency`/`num_workers`** (a real cap
knob), **reducer / `collect_events` barrier** (formalizing fan-in), **`defer=True`
synthesis node** (interflux's delegated-synthesis is conceptually this), and
**checkpointer** (interflux currently has no resume).

Deprecation note (FDR): Microsoft **AutoGen is in maintenance mode** → migrate to MAF;
OpenAI **Swarm** is superseded by the **Agents SDK**. No deprecation flags on the core
patterns interflux uses (semaphore, exp-backoff+jitter, orchestrator-worker, map-reduce).

## 4. How interflux compares (per-subtopic)

Internal mechanisms cited from repo-research-analyst (RRA) and learnings-researcher (LR)
with file:line; external practice as above.

### Fan-out / fan-in — ALIGNED, arguably richer
- **Match.** flux-drive is textbook orchestrator-worker: a host orchestrator fans out
  agents as parallel background `Task` calls (`skills/flux-engine/phases/launch.md:176-186`),
  workers don't talk to each other, and a dedicated synthesis step reconciles
  (`skills/flux-engine/phases/synthesize.md:45-108`). It even has **two** fan-out engines:
  single-run (flux-engine) and a nested multi-track fan-out
  (`skills/flux-review-engine/phases/track-dispatch.md:1-5,185-234`).
- **Match / exceeds.** "Scale effort to complexity" maps to flux-drive's dynamic slot
  ceiling (base 4 + scope + domain, hard max 10) and staged top-40% selection
  (`docs/spec/core/scoring.md:142-193`) — more principled than the framework heuristics.
- **Divergence (mechanism).** Where LangGraph supplies a `Send` primitive and a reducer
  for safe concurrent writes, interflux's fan-in safety comes from a **filesystem
  contract** instead: each agent writes its own `{agent}.md` via atomic rename
  (`skills/flux-engine/phases/shared-contracts.md:25-32`), so there is no shared-state
  clobber to reduce. This is a valid (and arguably more robust) alternative to reducers —
  isolation rather than merge — not a gap.

### Concurrency & rate-limit control — PARTIAL: capped, but not mechanically enforced
- **Match (intent).** flux-drive caps concurrency via `MAX_CONCURRENT_AGENTS` (default 6;
  env → `budget.yaml` → 6) and a nested cap for multi-track
  (`MAX_CONCURRENT_TRACKS=4` × `PER_TRACK_AGENT_CAP=3` = 12) precisely to stay inside the
  shared per-minute limit (`launch.md:156-174`;
  `skills/flux-review-engine/phases/track-dispatch.md:185-196`). This is exactly the
  "reserve for the whole workflow / nested fan-out math" best practice (Portkey/TrueFoundry).
- **Divergence (the central one).** The cap is **LLM-followed prose, not an enforced
  semaphore or work-queue** — "track in-flight Task calls and block when count ≥ cap" is an
  *instruction to the host model* (`launch.md:166-172`), with no runtime primitive
  guaranteeing it (RRA Gaps). Best practice (newline/rednafi/LlamaIndex/LangGraph) is a
  mechanical `Semaphore(N)` / `num_workers` / `max_concurrency`. Drift between spec and
  execution is possible and unmeasured.
- **Divergence (unsourced numbers).** The "why 6" rationale rests on an **Erlang-C claim
  ("~30% retry-token waste at the 16-agent tier") with no cited measurement or model
  parameters in-repo** (`launch.md:158,172`; RRA & LR both flag this) — design rationale,
  not validated telemetry.
- **No gateway.** interflux has no shared-key gateway/token-bucket coordinator; the
  OpenRouter free-tier 20-req/min handling is an **open, undecided question**
  (`docs/brainstorms/2026-04-09-multi-model-activation-brainstorm.md:50`; LR).

### Staged dispatch — ALIGNED (matches Anthropic's own design)
- **Strong match.** Review mode is two-stage by design: Stage 1 = top-40% scored (min 2,
  max 5), Stage 2 = conditional expansion gated by severity×adjacency thresholds (≥3
  recommend / 2 offer / ≤1 stop) and **always requires user approval — never auto-expands**
  (`docs/spec/core/staging.md:62-163`; `docs/spec/core/scoring.md:168-193`). This is exactly
  Anthropic's deliberately-chosen **synchronous wave dispatch** tradeoff (simplicity + clean
  fan-in), and interflux goes further with an inter-stage research-enrichment step and an
  **AgentDropout** redundancy filter (0.6 threshold, exempt fd-safety/fd-correctness;
  `staging.md:165-197`) — a width-reduction mechanism with no direct framework equivalent.
  Research mode is single-stage (all agents at once, `launch.md:52-56`), consistent with the
  "≥10 subagents for complex research" guidance.

### Partial-failure handling — ALIGNED on degradation; DIVERGES on backoff & resume
- **Match / exceeds.** flux-drive's partial-failure story is unusually thorough:
  an invariant that every launched agent yields exactly one `.md` (findings/error/stall
  stub) so synthesis always processes N files
  (`docs/spec/contracts/completion-signal.md:58-68`); a **Retry Race Protocol** (abort
  marker + rename-out-of-the-way so a slow original's late `mv` fails harmlessly, then one
  synchronous retry; `shared-contracts.md:83-111`); **synthetic-refusal detection** with
  auto-retry at a downgraded model tier (`launch.md:272-307`); **foreign-file detection**
  via run-UUID quire-mark (`launch.md:17-24`); and **graceful degradation** — error/stall
  stubs count but contribute zero findings, surviving tracks proceed
  (`synthesize.md:38-39`; `track-dispatch.md:183`). This directly satisfies the
  "synthesize from the subset that succeeded" best practice and is richer than the implicit
  degradation in most SDKs.
- **Divergence (no 429 backoff).** There is **no exponential-backoff+jitter on rate-limit
  errors at the dispatch layer**. interflux uses **block-on-cap backpressure** as its only
  rate defense; backoff+jitter exists in-repo only as advice for *reviewed code*
  (`agents/review/references/concurrency-patterns.md`), not in the dispatcher (LR Gaps).
  Best practice treats exp-backoff+jitter as the consensus 429 strategy and immediate
  retry as an anti-pattern.
- **Divergence (no checkpoint-resume).** flux-drive retries a failed *agent* but does not
  persist orchestrator plan/state for **resume after a crash** — there is no checkpointer /
  event-history replay (cf. LangGraph checkpointers, Temporal/Inngest). Anthropic's
  "save the plan before the context window fills" and durable-execution resume are
  unmatched. (interflux's atomic-rename contract is excellent for *completion detection*,
  but it is not a resumable workflow log.)

### Result synthesis — ALIGNED, the strongest area
- **Strong match / exceeds.** Synthesis is a **dedicated, delegated step** — the host never
  reads agent files; it hands the entire fan-in to an external **intersynth** subagent
  (`synthesize-review` / `synthesize-research`) that collects, validates, deduplicates,
  tracks convergence, and writes a deterministic verdict
  (`synthesize.md:45-108`). This is the "dedicated synthesis owned by the orchestrator" +
  "structured condensed returns" best practice, implemented as a clean `defer`-style barrier.
- **Match (dedup/convergence > framework aggregation).** Five dedup rules
  (same file:line+issue → merge & credit all; same line+diff issue → co-located; same
  issue+diff location → cross-reference; conflicting severity → highest; conflicting
  recommendation → **preserve both**) (`synthesize.md:110-119`;
  `docs/spec/core/synthesis.md:54-80`). **Convergence** (N agents agreeing) as the confidence
  signal, with cross-track convergence ranked highest
  (`skills/flux-review-engine/phases/track-synthesis.md:1-100`), directly realizes the
  "preserve disagreement / voting / cross-family agreement" guidance — and is far more
  developed than the "aggregation happens in the manager" model of OpenAI SDK/CrewAI/AG2.
- **Divergence / opportunity.** interflux's verdict is **deterministic rule-based** (any P0
  → risky; any P1 → needs-changes; else safe — `synthesize.md:218`), not an **LLM-as-judge**
  for termination control — the research's "judge is highest-leverage for *are we done*"
  point. interflux's expansion-decision scoring is the closest analog but is severity-driven,
  not a judge. Also, unlike Anthropic, there is **no separate citation/attribution agent** —
  attribution is folded into dedup credit, not a distinct verification pass. Finally,
  cross-track convergence is described qualitatively with **no numeric formula** equivalent
  to the single-run dedup rules (`track-synthesis.md:36-43`; RRA Gaps).

## 5. Recommendations (prioritized)

1. **Add a mechanical concurrency primitive (HIGH).** Replace "host tracks in-flight Tasks"
   prose with an enforced cap — a real semaphore / work-queue, mirroring LlamaIndex
   `num_workers` or LangGraph `max_concurrency`. Even a small dispatcher script holding a
   counted slot would close the spec-vs-execution drift flagged in
   `launch.md:166-172`/RRA Gaps. Highest leverage because today's cap is best-effort.
2. **Exponential backoff + jitter on 429 at the dispatch layer (HIGH).** Add per-error-class
   retry (transient → backoff+jitter, permanent → fail fast) to the dispatch loop, not just
   to reviewed-code guidance. Resolves the open OpenRouter 20-req/min question
   (`brainstorm:50`) and the LR-noted absence of dispatch-layer 429 handling. Pair with the
   semaphore so retries don't re-overshoot.
3. **Source or re-derive the Erlang-C numbers (MEDIUM).** Either cite a measurement /
   capture the model parameters behind "~30% retry-token waste at 16 agents" and "why 6", or
   relabel them as heuristics. Both RRA and LR flag these as unsourced
   (`launch.md:158-172`).
4. **Checkpoint-resume for the orchestrator (MEDIUM).** Persist the dispatch plan + stage
   state (the atomic-rename `.md` files already give per-agent durability; add a small
   run-manifest) so an interrupted run resumes Stage 2 rather than restarting — the
   LangGraph-checkpointer / Temporal pattern. Cheap given the existing filesystem contract.
5. **Optional LLM-as-judge for termination control (MEDIUM-LOW).** Augment the deterministic
   verdict with a judge that decides "is this review/research complete or should we expand?"
   — the research's highest-leverage synthesis use. interflux's expansion decision is the
   natural insertion point.
6. **Formalize cross-track convergence scoring (LOW).** Give multi-track fan-in a numeric
   convergence formula and dedup rules equivalent to the single-run five
   (`track-synthesis.md:36-43`).
7. **Consider a separate citation/attribution pass (LOW).** Anthropic's CitationAgent split
   improves reliability; interflux folds attribution into dedup credit. A distinct
   verification pass over `findings.json` is a possible robustness gain.
8. **Borrow vocabulary, not necessarily code (LOW).** Adopt the framework terms
   (`max_concurrency`, reducer/`collect_events` barrier, `defer` synthesis node,
   checkpointer) in the spec to make flux-drive legible to contributors coming from
   LangGraph/LlamaIndex.

## 6. Sources

**External (WebSearch/WebFetch fallback; Exa/Context7 unavailable):**

1. Anthropic — "How we built our multi-agent research system" — https://www.anthropic.com/engineering/built-multi-agent-research-system (primary; orchestrator-worker, subagent counts, ~90% time cut, synchronous waves, save-plan-before-context-limit, CitationAgent).
2. Anthropic, secondary summaries — https://blog.bytebytego.com/p/how-anthropic-built-a-multi-agent ; https://www.zenml.io/llmops-database/building-a-multi-agent-research-system-for-complex-information-tasks
3. LangGraph Map-Reduce / Send API — https://deepwiki.com/langchain-ai/langchain-academy/7.1-map-reduce-pattern ; https://machinelearningplus.com/gen-ai/langgraph-map-reduce-parallel-execution/ ; https://markaicode.com/langgraph-parallel-fan-out-fan-in/
4. LangGraph "Use the graph API" (Send/reducers/supersteps/max_concurrency/recursion_limit/defer) — https://docs.langchain.com/oss/python/langgraph/use-graph-api
5. LangGraph Durable Execution (checkpointers) — https://docs.langchain.com/oss/python/langgraph/durable-execution
6. OpenAI Agents SDK — orchestration / handoffs / cookbook — https://openai.github.io/openai-agents-python/multi_agent/ ; https://openai.github.io/openai-agents-python/handoffs/ ; https://cookbook.openai.com/examples/agents_sdk/parallel_agents
7. AG2 v0.9 Group Chat — https://docs.ag2.ai/latest/docs/blog/2025/04/28/0.9-Release-Announcement/ ; https://docs.ag2.ai/latest/docs/user-guide/advanced-concepts/orchestration/group-chat/
8. Microsoft AutoGen → Agent Framework migration — https://learn.microsoft.com/en-us/agent-framework/migration-guide/from-autogen/ ; https://learn.microsoft.com/en-us/agent-framework/overview/
9. CrewAI Processes / async kickoff — https://docs.crewai.com/en/concepts/processes ; https://docs.crewai.com/en/learn/kickoff-async ; https://docs.crewai.com/how-to/kickoff-for-each
10. LlamaIndex Workflows (send_event/num_workers/collect_events) — https://developers.llamaindex.ai/python/examples/workflow/parallel_execution/ ; https://developers.llamaindex.ai/python/llamaagents/workflows/concurrent_execution/
11. Portkey — "Rate limiting for LLM applications" — https://portkey.ai/blog/rate-limiting-for-llm-applications/
12. TrueFoundry — "Rate Limiting AI Agents: 3-Layer Gateway" — https://www.truefoundry.com/blog/rate-limiting-ai-agents-preventing-llm-api-exhaustion
13. SparkCo — "Mastering Retry Logic Agents (2025)" ; apxml — "Manage API Rate Limits in Tools" — https://sparkco.ai/blog/mastering-retry-logic-agents-a-deep-dive-into-2025-best-practices ; https://apxml.com/courses/building-advanced-llm-agent-tools/chapter-4-integrating-external-apis-tools/api-rate-limits-retries-tools
14. asyncio concurrency for LLMs — https://www.newline.co/@zaoyang/python-asyncio-for-llm-concurrency-best-practices--bc079176 ; https://rednafi.com/python/limit_concurrency_with_semaphore/
15. Inngest — "Durable Execution…" ; Temporal — "…dynamic AI agents with Temporal" — https://www.inngest.com/blog/durable-execution-key-to-harnessing-ai-agents ; https://temporal.io/blog/of-course-you-can-build-dynamic-ai-agents-with-temporal
16. "LLM-as-a-Judge in Multi-Agent Systems" (Medium, Apr 2026) ; "LLMs-as-Judges: A Comprehensive Survey" — https://medium.com/@balajibal/llm-as-a-judge-in-multi-agent-systems-where-it-works-how-to-build-it-and-why-the-flow-matters-02f0b9a6dc47 ; https://arxiv.org/pdf/2412.05579
17. AgentDropout — arXiv:2503.18891 (cited in-repo at `docs/spec/core/staging.md` for the redundancy filter).

**Internal (interflux repo, file:line):**

18. `skills/flux-engine/phases/launch.md:156-174` — concurrency cap, Erlang-C rationale, dispatch loop.
19. `skills/flux-engine/phases/launch.md:176-186` — Stage 1 launch (top 2-3, `run_in_background`).
20. `skills/flux-engine/phases/launch.md:52-56` — research-mode single-stage dispatch.
21. `skills/flux-engine/phases/launch.md:262-307` — monitoring, stall rescue, retry race, synthetic-refusal + tier-downgrade.
22. `skills/flux-engine/phases/launch.md:17-24` — run-UUID (quire-mark).
23. `skills/flux-engine/phases/shared-contracts.md:25-32` — atomic `.partial`→`.md` completion signal.
24. `skills/flux-engine/phases/shared-contracts.md:35-111` — Dispatch State Machine + Retry Race Protocol.
25. `skills/flux-engine/phases/synthesize.md:45-119` — delegated intersynth synthesis + 5 dedup rules.
26. `skills/flux-engine/phases/expansion.md:305` — Stage 2 batched dispatch respecting the cap.
27. `skills/flux-review-engine/SKILL.md:69-88` — track-count triage.
28. `skills/flux-review-engine/phases/track-dispatch.md:1-5,167-234` — two-phase fan-out, nested caps (4×3), partial-track degradation.
29. `skills/flux-review-engine/phases/track-synthesis.md:1-100` — cross-track fan-in + convergence ranking.
30. `docs/spec/core/scoring.md:13-193` — score formula, dynamic slot ceiling, Stage assignment.
31. `docs/spec/core/staging.md:62-197` — adjacency map, expansion scoring/thresholds, AgentDropout (0.6, exempt fd-safety/fd-correctness).
32. `docs/spec/core/synthesis.md:11-80,150-205,422` — validation, index-first collection, dedup, convergence weighting, deterministic verdict, graceful degradation.
33. `docs/spec/contracts/completion-signal.md:11-89` — atomic-rename contract, poll/timeout/retry, error stub, exactly-one-`.md` invariant.
34. `docs/solutions/2026-04-14-fleet-drift-coordination.md:19-23` — atomic counter discipline under concurrent sessions.
35. `docs/brainstorms/2026-04-09-multi-model-activation-brainstorm.md:50` — open OpenRouter 20-req/min queue-vs-cap question.
36. `agents/review/references/concurrency-patterns.md` — backoff+jitter/errgroup/allSettled (guidance for reviewed code, not the engine).

## 7. Confidence & Gaps

**Overall confidence: High** on the comparison's structure and the internal mechanisms;
**Medium** on some external specifics.

- **Internal findings: High.** Every flux-drive mechanism is documented in dedicated,
  internally consistent spec + skill files with concrete parameters and worked examples,
  and the two engines cross-reference coherently (RRA, LR both High). Caveat: confidence is
  High for *what the protocol specifies*; necessarily lower for *what executes at runtime*,
  because orchestration is prose-instruction-driven — adherence depends on the host model
  (RRA Gaps).
- **External findings: High for core patterns** (orchestrator-worker, Send/reducers,
  num_workers/collect_events, exp-backoff+jitter, synchronous waves) — they converge across
  a primary vendor writeup, two framework docs, durable-execution docs, and multiple
  practitioner guides. **Medium** for quantitative knobs (exact semaphore size, "10-20%
  below limit") — sensible heuristics, not standardized.

**Unverified / open:**
- **Exa/Context7 unavailable** — external sources are WebFetch summaries, not byte-for-byte
  verified pages. The Anthropic numbers (1/2-4/10+ subagents, 90%, 15x, 200k) come from a
  WebFetch extraction plus corroborating secondaries; raw page text not seen.
- **No primary CrewAI Flows / LangGraph RetryPolicy / MAF GA version** fully fetched —
  flagged in FDR Gaps; confirm via release notes before quoting versions.
- **interflux runtime adherence is unmeasured** — no telemetry comparing specified vs actual
  concurrency, and the Erlang-C "~30%/why-6" figures have no in-repo derivation.
- **Dedup fuzzy-match thresholds and cross-track convergence scoring** live inside the
  intersynth subagent's context with no deterministic in-repo implementation to inspect; no
  specified behavior if intersynth is unavailable (RRA Gaps).
- **Adjacency map is hardcoded/unlearned and omits the 5 cognitive agents** (RRA Gaps) —
  out of scope for this orchestration question but relevant to expansion behavior.

<!-- flux-research:complete -->
