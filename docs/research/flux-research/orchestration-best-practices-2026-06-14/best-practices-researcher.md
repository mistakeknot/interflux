# Best Practices: Multi-Agent LLM Orchestration (fan-out/fan-in, concurrency, staged dispatch, partial failure, synthesis)

Research date: 2026-06-14. Exa MCP unavailable this session; used WebSearch + WebFetch (documented progressive-enhancement fallback).

### Sources

1. **Anthropic — "How we built our multi-agent research system"** — https://www.anthropic.com/engineering/built-multi-agent-research-system — Primary source, vendor engineering blog. The canonical production writeup of orchestrator-worker LLM research; concrete numbers on subagent counts, parallelism, token economics. Highest authority for this question.
2. **Anthropic multi-agent system, secondary analysis (ByteByteGo / TheAIEngineer / ZenML LLMOps DB)** — https://blog.bytebytego.com/p/how-anthropic-built-a-multi-agent ; https://www.zenml.io/llmops-database/building-a-multi-agent-research-system-for-complex-information-tasks — Reputable secondary summaries corroborating #1 (orchestrator-worker, parallel subagents, shared memory, citation agent).
3. **LangGraph — Map-Reduce / Send API (LangChain Academy, machinelearningplus, Markaicode)** — https://deepwiki.com/langchain-ai/langchain-academy/7.1-map-reduce-pattern ; https://machinelearningplus.com/gen-ai/langgraph-map-reduce-parallel-execution/ ; https://markaicode.com/langgraph-parallel-fan-out-fan-in/ — Framework docs/tutorials. Authoritative on dynamic fan-out (`Send`), fan-in via state reducers, independent worker state.
4. **LangGraph — Durable Execution (official docs)** — https://docs.langchain.com/oss/python/langgraph/durable-execution — Primary framework docs. Checkpointers as thread-scoped memory enabling fault tolerance / resume; durability modes referenced.
5. **OpenAI Agents SDK — Agent orchestration (official docs + cookbook)** — https://openai.github.io/openai-agents-python/multi_agent/ ; https://cookbook.openai.com/examples/agents_sdk/parallel_agents — Primary framework docs. Two patterns: "agents-as-tools" (manager/orchestrator) vs "handoffs" (decentralized); parallelism via `asyncio.gather`.
6. **Portkey — "Rate limiting for LLM applications"** — https://portkey.ai/blog/rate-limiting-for-llm-applications/ — Gateway vendor blog. Backoff+retry, queue/stagger batch workloads, gateway-level centralized limiting, multi-provider distribution.
7. **TrueFoundry — "Rate Limiting AI Agents: Preventing LLM API Exhaustion with a 3-Layer Gateway"** — https://www.truefoundry.com/blog/rate-limiting-ai-agents-preventing-llm-api-exhaustion — Vendor engineering blog. Retry-storm dynamics under concurrent agents; reserve quota for whole workflows.
8. **SparkCo — "Mastering Retry Logic Agents: 2025 Best Practices"** + **apxml — "Manage API Rate Limits in Tools"** — https://sparkco.ai/blog/mastering-retry-logic-agents-a-deep-dive-into-2025-best-practices ; https://apxml.com/courses/building-advanced-llm-agent-tools/chapter-4-integrating-external-apis-tools/api-rate-limits-retries-tools — Practitioner guides. Exponential backoff + jitter, per-error-class retry policy.
9. **Python asyncio concurrency for LLMs (newline, rednafi, soumendrak)** — https://www.newline.co/@zaoyang/python-asyncio-for-llm-concurrency-best-practices--bc079176 ; https://rednafi.com/python/limit_concurrency_with_semaphore/ — Practitioner guides. `asyncio.Semaphore` to cap concurrency; semaphore sizing vs RPM; batching vs concurrency.
10. **Inngest — "Durable Execution: The Key to Harnessing AI Agents in Production"** + **Temporal — "Of course you can build dynamic AI agents with Temporal"** — https://www.inngest.com/blog/durable-execution-key-to-harnessing-ai-agents ; https://temporal.io/blog/of-course-you-can-build-dynamic-ai-agents-with-temporal — Durable-execution vendor blogs. Event-history replay, automatic retry, suspend/resume, idempotency keys for side effects.
11. **"LLM-as-a-Judge in Multi-Agent Systems" (Medium, balaji bal, Apr 2026)** + **"LLMs-as-Judges: A Comprehensive Survey" (arXiv 2412.05579)** — https://medium.com/@balajibal/llm-as-a-judge-in-multi-agent-systems-where-it-works-how-to-build-it-and-why-the-flow-matters-02f0b9a6dc47 ; https://arxiv.org/pdf/2412.05579 — Practitioner + peer-style survey. Synthesis/judge patterns: weighted averaging, voting, panel/debate; preserve disagreement, judge for termination control.

---

### Findings

#### A. Orchestrator-Worker is the dominant production topology
- The orchestrator-worker (lead-agent + subagents) pattern is the de-facto standard for fan-out research/review work. A lead agent analyzes the query, plans, spawns parallel subagents each with its own context window and tools, then synthesizes [1, 2]. The two mainstream SDK encodings are **"agents-as-tools / manager"** (orchestrator keeps control, calls subagents like tools) and **"handoffs"** (decentralized peer transfer); the manager pattern is preferred when you want centralized fan-in and a single synthesis point [5].
- *Recommended.* Use centralized orchestration when results must be reconciled into one output (the review/research case); use handoffs only when one specialist should fully own the rest of the task.

#### B. Fan-out / fan-in
- **Dynamic fan-out**: LangGraph's `Send` API is the reference pattern — emit an arbitrary, runtime-determined number of `Send(node, state)` objects to launch N parallel workers when the item count is not known in advance (multi-source research, batch labeling, parallel tool calls) [3].
- **Fan-in**: merge concurrent worker outputs through a **state reducer** (e.g. `operator.add` on a list) so parallel writes don't clobber each other; workers should use an **independent worker-state schema** decoupled from the parent graph [3]. This is the structural fix for the classic "concurrent state update" bug in parallel nodes.
- **Scale effort to complexity** (Anthropic's explicit guidance): ~1 agent for simple fact-finding, 2-4 for direct comparisons, 10+ for complex research with divided responsibilities. Spinning up 3-5 subagents in parallel (each calling 3+ tools in parallel) cut research time ~90% on complex queries vs serial execution [1].
- In SDKs without a graph engine, fan-out is just `asyncio.gather` over independent agent runs; build an explicit graph with `gather` when you need to customize multi-layer fan-out/fan-in, but note the upfront planning + context overhead if latency-sensitive [5].

#### C. Concurrency & rate-limit control
- **Cap concurrency with a semaphore.** `asyncio.Semaphore(N)` is the standard primitive to bound simultaneous in-flight LLM calls; size N relative to your RPM budget (e.g. ~10 concurrent for a 60 RPM plan) and lower N at high volume to avoid a "thundering herd" overshooting the limit [9, 6].
- **Distinguish concurrency-limiting from batching.** Semaphore caps how many run at once (e.g. max 5); batch processors slice the workload into groups (e.g. 20-50) and/or combine items into fewer larger calls (e.g. one batched embedding request of 10 items). Use both together for high-volume fan-out [9, 6].
- **Stay below the ceiling proactively.** Track requests/tokens per minute and stay ~10-20% under provider limits; **reserve quota for an entire multi-step workflow before starting it** rather than per-call, so a long agent run doesn't stall mid-flight [6, 7].
- **Centralize limiting at a gateway** when multiple agents/users share a key — gateway-level (often Redis/token-bucket) quota coordination prevents one agent from starving others, and enables multi-provider traffic distribution as a pressure-release valve [6, 7].

#### D. Retries & backoff for rate limits / transient errors
- **Exponential backoff + jitter** is the consensus retry strategy for 429s/transient failures; jitter is essential to prevent synchronized "retry storms" across many concurrent agents [8, 6].
- **Immediate/minimal-backoff retries on 429 are an anti-pattern** under concurrency — they generate more 429s and burn the rate-limit budget while making no progress [7].
- **Per-error-class policy, not one catch-all.** Classify transient (retry with backoff) vs permanent (fail fast, no retry) errors; define retry policy per class [8, 10].

#### E. Staged / wave dispatch
- Anthropic's production system dispatches subagents **synchronously in waves** — the lead waits for a wave to complete before deciding the next step. This is simpler to reason about and to synthesize, at the cost of head-of-line bottlenecks (the slowest subagent gates the wave); they call out async concurrent dispatch as a future improvement [1]. *Takeaway: wave/staged dispatch is a legitimate, deliberately-chosen tradeoff (simplicity + clean fan-in) rather than a deficiency — appropriate when synthesis needs a coherent snapshot of a stage's results.*
- Pair staged dispatch with the concurrency cap (C): within a wave, run workers in parallel up to the semaphore limit; across waves, let the orchestrator re-plan using accumulated state.

#### F. Partial-failure handling & durability
- **Persist the plan/state to external memory before context limits** (Anthropic saves the research plan before the ~200k-token window fills) so a failed/compacted agent can resume rather than restart [1].
- **Checkpoint + resume, don't restart.** Durable-execution model (Temporal/Inngest, and LangGraph checkpointers) records an event history / state snapshot keyed by a thread/workflow ID and **replays to resume at the exact failed step**, avoiding re-running completed work [10, 4, 1].
- **Idempotency is a prerequisite for safe checkpointing/retries.** Any tool with external side effects (create ticket, send email, charge) must carry an idempotency key tied to workflow state so replay/retry doesn't duplicate effects [10].
- **Graceful degradation in fan-in:** the orchestrator should tolerate individual subagent/tool failures and synthesize from the subset that succeeded (subagents act as adaptive "intelligent filters" that handle tool failures) rather than aborting the whole run [1, 2]. Durable suspend/resume also maps cleanly onto human-in-the-loop pauses [10].

#### G. Result synthesis / aggregation
- **Dedicated synthesis step owned by the orchestrator/lead.** Subagents return *structured, condensed* findings (often via a shared memory store rather than long chat returns); the lead reconciles them and decides whether more research is needed [1, 2].
- **Separate the citation/attribution step.** Anthropic runs a distinct CitationAgent after synthesis to map claims back to source documents — separating "synthesize" from "attribute" improves reliability [1].
- **Aggregation strategies** (pick per task): weighted averaging, majority voting, or panel/debate; for evaluation/ranking, LLM-as-judge over candidate outputs [11].
- **Preserve disagreement — don't flatten into fake consensus.** When subagents return partial truths from different domains, the synthesis should retain evidence and surface conflicts, not paper over them [11].
- **Judge is most valuable for termination control**, not just ranking — using a judge/orchestrator to decide "are we done / is this good enough" is often higher-leverage than scoring [11].

#### Deprecation sanity-check
- LangGraph `Send` API and checkpointers: current in 2026 LangGraph OSS docs [3, 4]. OpenAI **Agents SDK** (`openai-agents-python`) is the current, actively-documented successor to the earlier experimental **Swarm** project — recommend Agents SDK, treat Swarm as superseded [5]. Temporal/Inngest durable execution: actively current (durable execution called out as crossing into the early majority in 2025, with AWS/Cloudflare/Vercel entrants) [10]. No deprecation flags found on the core patterns recommended (semaphore concurrency, exp-backoff+jitter, orchestrator-worker, map-reduce fan-out).

---

### Confidence

**High** for the core patterns. The five subtopics converge across independent source types: a primary vendor production writeup (Anthropic [1]), two major framework docs (LangGraph [3,4], OpenAI Agents SDK [5]), durable-execution platform docs (Temporal/Inngest [10]), and multiple consistent practitioner guides on concurrency/rate-limiting [6,7,8,9]. The strongest, most concrete claims (subagent counts, ~90% time reduction, 15x token cost, wave dispatch, idempotency-before-checkpointing, exp-backoff+jitter, semaphore sizing) are directly attributable and mutually corroborated.

**Medium** for the precise quantitative knobs (exact semaphore size, exact "10-20% below limit" threshold) — these are sensible heuristics from practitioner blogs, not standardized, and depend on provider/plan.

---

### Gaps

- **Anthropic primary URL not byte-for-byte verified beyond WebFetch summary.** The numbers (1 / 2-4 / 10+ subagents, 3-5 parallel, 90%, 15x, 200k) come from a WebFetch extraction of the official page plus corroborating secondaries [1,2]; I did not see the raw page text, though multiple secondary sources agree.
- **LangGraph "durability modes" specifics not captured.** The official durable-execution page references a `durability-modes` anchor but the fetched content lacked that section [4]; exact mode names (e.g. sync/async/exit) and idempotency guidance live in the deeper Checkpointers guide I did not fetch.
- **No primary CrewAI / AutoGen (AG2) / LlamaIndex Workflows docs fetched** this session. Their orchestration models (CrewAI sequential/hierarchical processes, AutoGen group-chat, LlamaIndex event-driven workflows) are referenced in the question but not independently verified here — likely consistent with the orchestrator-worker + event/state patterns above, but unconfirmed.
- **Quantitative concurrency/rate-limit thresholds are heuristic**, not from provider SLAs; real limits should be read from the specific provider's current rate-limit docs before implementation.
- **Cost/latency tradeoff of staged vs fully-async dispatch** is described qualitatively (Anthropic notes the bottleneck) but I found no benchmark quantifying wave vs async overhead.

<!-- flux-research:complete -->
