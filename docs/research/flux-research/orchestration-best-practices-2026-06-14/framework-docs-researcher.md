# Framework-Specific Orchestration Mechanisms: Fan-Out/Fan-In, Concurrency Control, Result Aggregation

Research date: 2026-06-14. Focus: documented, version-specific orchestration primitives across major
multi-agent / agent-orchestration frameworks. MCP (Context7/Exa) was unavailable; this used WebSearch +
WebFetch against official docs (documented progressive-enhancement fallback).

### Sources

1. **LangGraph** — "Use the graph API" (Graph API / Send API / reducers / concurrency), docs.langchain.com (LangChain OSS Python docs). https://docs.langchain.com/oss/python/langgraph/use-graph-api
2. **OpenAI Agents SDK** — "Agent orchestration" (handoffs vs agents-as-tools, code-based orchestration). https://openai.github.io/openai-agents-python/multi_agent/ ; Handoffs: https://openai.github.io/openai-agents-python/handoffs/ ; repo: https://github.com/openai/openai-agents-python
3. **AG2 (community fork of AutoGen)** — "AG2 v0.9 Release: Introducing the New Group Chat Pattern" (released 2025-04-28). https://docs.ag2.ai/latest/docs/blog/2025/04/28/0.9-Release-Announcement/ ; Group chat: https://docs.ag2.ai/latest/docs/user-guide/advanced-concepts/orchestration/group-chat/ ; API: https://docs.ag2.ai/docs/api-reference/autogen/GroupChat
4. **Microsoft AutoGen → Microsoft Agent Framework (MAF)** — "AutoGen to Microsoft Agent Framework Migration Guide", Microsoft Learn (page dated/updated 2026-04-01/02). https://learn.microsoft.com/en-us/agent-framework/migration-guide/from-autogen/ ; MAF overview: https://learn.microsoft.com/en-us/agent-framework/overview/ ; autogen-core (legacy) teams API: https://microsoft.github.io/autogen/stable//reference/python/autogen_agentchat.teams.html ; repo: https://github.com/microsoft/autogen
5. **CrewAI** — "Processes" (sequential vs hierarchical, manager_llm/manager_agent). https://docs.crewai.com/en/concepts/processes ; "Kickoff Crew Asynchronously": https://docs.crewai.com/en/learn/kickoff-async ; "Kickoff Crew for Each": https://docs.crewai.com/how-to/kickoff-for-each
6. **LlamaIndex Workflows** — "Parallel Execution of Same Event Example" (ctx.send_event / num_workers / ctx.collect_events). https://developers.llamaindex.ai/python/examples/workflow/parallel_execution/ ; Concurrent execution: https://developers.llamaindex.ai/python/llamaagents/workflows/concurrent_execution/ ; Workflow API ref: https://developers.llamaindex.ai/python/workflows-api-reference/workflow/
7. **Anthropic** — "How we built our multi-agent research system" (orchestrator-worker, parallel subagents). https://www.anthropic.com/engineering/built-multi-agent-research-system ; "Building Effective AI Agents": https://www.anthropic.com/research/building-effective-agents

### Findings

**1. LangGraph (LangChain OSS) — graph + Send API. The most explicit fan-out/fan-in primitives of any framework here.**
- **Fan-out (dynamic map):** A routing function returns a list of `Send(node_name, state)` objects (`from langgraph.types import Send`). Each `Send` spawns one parallel instance of the target node with its own payload. This enables map-reduce where the number of branches is unknown until runtime — e.g. `return [Send("generate_joke", {"subject": s}) for s in state["subjects"]]`.
- **Fan-in (reduce):** State keys declare a reducer via `Annotated[list, operator.add]` so concurrent writes from many branches merge safely (append) rather than clobber. Built-in `add_messages` reducer merges message lists.
- **Execution model:** Nodes run in **supersteps** — transactional boundaries; a superstep completes only when all parallel branches in it finish (fan-in barrier). Note in docs: "updates from a parallel superstep may not be ordered consistently."
- **Concurrency control:** `graph.invoke(state, {"configurable": {"max_concurrency": 10}})` caps simultaneous tasks.
- **Loop / safety limit:** `recursion_limit` (default config) bounds the number of supersteps; exceeding raises `GraphRecursionError`. `RemainingSteps` annotation lets a node end gracefully before hitting it.
- **Uneven-branch fan-in:** mark a node `defer=True` (`builder.add_node("d", node_d, defer=True)`) so it executes only after all pending parallel tasks complete — the canonical fan-in/synthesis node.
- Retry/backoff: per-node retry policies exist in the API (RetryPolicy) but were not on the page fetched.

**2. OpenAI Agents SDK (Python) — small primitive set; orchestration is "code-driven" with asyncio.**
- Two delegation patterns: **Handoffs** (control transfers to a specialist agent that then owns the interaction; routing IS the workflow) vs **Agents-as-tools** (`Agent.as_tool()` — a manager keeps control, calls specialists as tools, and owns the final synthesized answer). Agents-as-tools is the documented choice for "one agent owns the final answer" + combining multiple experts.
- **Fan-out/concurrency:** No bespoke parallel primitive — docs explicitly say use **Python primitives like `asyncio.gather`** to run independent agents simultaneously. `Runner.run` (async) drives a single agent loop; parallelism is the caller's responsibility.
- **Other documented orchestration building blocks:** structured outputs for routing/classification, agent chaining (output→input), and evaluator feedback loops (`while` loop with an eval agent).
- **Synthesis/aggregation:** No explicitly named synthesis primitive — aggregation happens implicitly in the manager when using agents-as-tools.
- Lineage note: this SDK is the production successor to the experimental **Swarm** (handoffs concept originates there); Swarm itself is an educational/experimental repo, not for production.

**3. AG2 (community-maintained AutoGen fork) — GroupChat patterns; turn-based, NOT concurrent.**
- **v0.9 (2025-04-28)** unified the old GroupChat and Swarm into one Group Chat orchestrated by a `GroupChatManager`.
- **Speaker-selection patterns (the orchestration primitive):** `AutoPattern` (LLM picks next speaker from context), `RoundRobinPattern` (fixed rotation), `RandomPattern`, `ManualPattern` (human-in-the-loop), `DefaultPattern` (explicit handoff control). Transitions route to targets: `AgentTarget`, `RevertToUserTarget`, `TerminateTarget`, `StayTarget`, `RandomAgentTarget`, `GroupChatTarget`. "After-work" behavior defines post-completion routing.
- **Concurrency:** Architecture is **sequential / turn-based speaker selection — no built-in parallel agent execution.** Docs only reference `parallel_tool_calls: False` in LLMConfig (a tool-call setting, not agent fan-out). Fan-out/fan-in across agents is not a native AG2 concept.

**4. Microsoft AutoGen → Microsoft Agent Framework (MAF) — DEPRECATION FINDING.**
- **AutoGen (microsoft/autogen) is in maintenance mode.** Microsoft's official Learn migration guide (updated 2026-04) directs new production work to the **Microsoft Agent Framework (MAF)**, built by the combined AutoGen + Semantic Kernel teams, unifying both. Treat AutoGen's `autogen_agentchat.teams` (RoundRobinGroupChat, etc.) as legacy.
- **AutoGen's legacy orchestration:** event-driven core + high-level `Team` abstraction (e.g. `RoundRobinGroupChat`, `MagenticOneGroupChat`). When wrapping agents as tools you had to set `parallel_tool_calls=False` on the coordinator to avoid concurrency issues with a shared stateful agent instance.
- **MAF's model (the successor primitive):** a typed, **graph-based `Workflow`** — data-flow based, where messages route along **typed edges** and **executors** (agents, functions, or sub-workflows) activate when their inputs are ready. Built via `WorkflowBuilder(start_executor=...).add_edge(...).build()`; run with `await workflow.run(...)`. Per the migration guide, Workflow "supports concurrent execution," request/response pauses, and checkpointing. It evolves AutoGen's experimental `GraphFlow` from control-flow (conditional transitions/broadcasts) to data-flow (edge-activated executors). MAF's `as_tool()` does NOT require disabling parallel tool calls (agents stateless by default) — an explicit improvement over AutoGen.
- Migration guide is dated `ms.date: 2026-04-01`; community sources flag a practical push to migrate before legacy async/callback patterns lose ecosystem support (~Q3 2026) — verify the exact MAF GA version independently (see Gaps).

**5. CrewAI — Process types + crew-level async; concurrency is coarse-grained.**
- **Process types (`from crewai import Process`):** `Process.sequential` (task output feeds next task as context) and `Process.hierarchical` (a manager delegates/validates). Hierarchical **requires** `manager_llm="gpt-4o"` (or similar) OR a custom `manager_agent`; the manager plans, delegates, reviews outputs, validates completion. (`Process.consensual` is referenced in community docs but is roadmap/experimental.)
- **Fan-out across inputs:** `crew.kickoff_for_each(inputs=[...])` runs the crew once per input; `kickoff_for_each_async()` does so concurrently. For native async there is `kickoff_async()` / `akickoff()` ("true native async throughout the entire execution chain," recommended for high-concurrency, per the kickoff-async docs).
- **Task-level parallelism:** `async_execution=True` on a Task lets it run concurrently relative to other tasks in the same crew.
- **Flows** (separate from Process): a `Flow` class with `@start`, `@listen`, `@router` decorators orchestrates arbitrary mixtures of crews/agents/Python — the recommended primitive for complex control flow. (Not fetched from official Flows page; see Gaps.)
- **Aggregation:** no named reduce primitive; results collected by the manager (hierarchical) or by Python code in a Flow.

**6. LlamaIndex Workflows — event-driven; the cleanest explicit fan-out → control → fan-in triad besides LangGraph.**
- **Fan-out:** emit multiple events from a step via `ctx.send_event(Event(...))` in a loop — distributes work across many event instances.
- **Concurrency control:** `@step(num_workers=N)` caps how many instances of that step run simultaneously (default `num_workers=4`). Docs measured ~7.4s at `num_workers=1` vs ~2.6s at `num_workers=3` for the same workload, and caution that "`num_workers` cannot be set without limits. It depends on your workload or token limits."
- **Fan-in:** `results = ctx.collect_events(ev, [ResultEvent] * N)` buffers until N matching events arrive, returning `None` until the barrier is met, then yields the collected list for synthesis.
- **State safety:** docs warn shared state under parallel steps must be updated thread-safely; the framework gives the parallel mechanism but not automatic merge semantics (contrast LangGraph reducers).

**7. Anthropic — guidance/architecture (not a code framework), but the most directly relevant design pattern.**
- **Pattern:** orchestrator-worker. A **lead/orchestrator agent** ("LeadResearcher") decomposes the query and **spawns subagents in parallel**, each with its own context window, tools, and self-contained task description. "Workers never talk to each other; every decision about what comes next lives in the orchestrator."
- **Scale heuristics (documented):** simple query → 1 agent, 3-10 tool calls; comparisons → 2-4 subagents, 10-15 calls each; complex research → 10+ subagents. Lead spins up "3-5 subagents in parallel rather than serially; subagents use 3+ tools in parallel" — cited as cutting research time up to 90%.
- **Aggregation/synthesis:** the lead **synthesizes subagent results iteratively** and decides whether to spawn more subagents or refine strategy.
- **Concurrency limitation (honest caveat):** Anthropic's own implementation runs subagents **synchronously** — the lead waits for each batch to finish before proceeding; this simplifies coordination but bottlenecks information flow and prevents real-time steering. Reported ~90.2% improvement over single-agent on internal evals.
- Companion guidance ("Building Effective AI Agents") frames parallelization (sectioning + voting) and orchestrator-workers as distinct workflow patterns.

**Cross-framework synthesis (concurrency-control taxonomy):**
- Explicit cap primitives: LangGraph `max_concurrency`; LlamaIndex `@step(num_workers=N)`. These are the only two with a first-class concurrency-limit knob in the fetched docs.
- Safe-merge fan-in: LangGraph reducers (`operator.add` / `add_messages`) and `defer=True` barrier; LlamaIndex `ctx.collect_events` barrier. Others (CrewAI, OpenAI SDK, AG2) leave aggregation to a manager agent or hand-written code.
- Caller-driven parallelism (no framework primitive): OpenAI Agents SDK (`asyncio.gather`), CrewAI (`kickoff_async`/`kickoff_for_each_async`, `async_execution`).
- Turn-based / no agent-level parallelism: AG2 GroupChat, legacy AutoGen Teams.
- Retry/backoff: not surfaced in fetched docs for most; LangGraph has per-node RetryPolicy (not verified on the page read). General LLM-call retry/backoff is typically left to the model client layer across all frameworks.

### Confidence

**High** for the named primitives and code-level mechanisms: LangGraph (Send/reducers/supersteps/max_concurrency/recursion_limit/defer), LlamaIndex (send_event/num_workers/collect_events, including default num_workers=4), OpenAI Agents SDK (handoffs vs as_tool, asyncio.gather), AG2 v0.9 patterns (version + pattern names from the official release post), Anthropic orchestrator-worker mechanics and the synchronous-execution caveat (from Anthropic's own engineering post), and CrewAI Process.sequential/hierarchical + manager_llm/manager_agent (official Processes page). These came from official/primary docs.

**Medium** for: the AutoGen → MAF deprecation status and MAF's `Workflow`/`WorkflowBuilder`/executor model — sourced from the official Microsoft Learn migration guide (primary, dated 2026-04), so the direction is solid, but exact MAF GA version number and timeline specifics were partly corroborated by secondary blogs. CrewAI async method names (`kickoff_async`/`akickoff`/`kickoff_for_each_async`/`async_execution`) come from official kickoff-async/kickoff-for-each pages but were read via search summary, not full fetch of each.

**Low** for: precise version numbers of LangGraph, LlamaIndex Workflows, CrewAI, and the OpenAI Agents SDK at time of writing (docs are rolling/un-versioned on the pages fetched); CrewAI Flows decorator details (`@start/@listen/@router`) came from a search summary, not the official Flows page; retry/backoff specifics across frameworks.

### Gaps

- **Exact current version strings** for LangGraph, LlamaIndex (workflows package), CrewAI, and OpenAI Agents SDK were not pinned — their docs are rolling and un-versioned on the pages read. Recommend confirming via PyPI / release notes before quoting a number.
- **Microsoft Agent Framework GA version** and the precise sunset/timeline for AutoGen legacy async patterns ("~Q3 2026") need verification against an official MAF release announcement (overview page fetched only as metadata).
- **LangGraph RetryPolicy / backoff** and durability/checkpointer interaction with concurrency not verified on the fetched page.
- **CrewAI Flows** (`@start/@listen/@router`, and any concurrency within flows) not read from the official Flows page — only from a search summary.
- **OpenAI Agents SDK** has no documented native synthesis/aggregation primitive; whether newer releases added structured parallel/aggregation helpers was not confirmed.
- **AG2 vs Microsoft AutoGen divergence:** AG2 (docs.ag2.ai) is a separate community fork; the Microsoft-branded autogen is the one in maintenance mode. Their roadmaps differ — claims about one should not be transferred to the other.
- Did not deep-verify **retry/backoff** mechanisms for AG2, CrewAI, LlamaIndex, or OpenAI SDK.

<!-- flux-research:complete -->
