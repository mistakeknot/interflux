### Sources

**Multi-agent Frameworks**
- [LangGraph official docs — parallel workflows and routing](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [LangGraph Multi-Agent Orchestration Guide 2025 — Latenode](https://latenode.com/blog/ai-frameworks-technical-infrastructure/langgraph-multi-agent-orchestration/langgraph-multi-agent-orchestration-complete-framework-guide-architecture-analysis-2025)
- [LangGraph AI Framework 2025 — Architecture Analysis](https://latenode.com/blog/langgraph-ai-framework-2025-complete-architecture-guide-multi-agent-orchestration-analysis)
- [Semantic Kernel: Multi-agent Orchestration — Microsoft devblog](https://devblogs.microsoft.com/semantic-kernel/semantic-kernel-multi-agent-orchestration/)
- [Semantic Kernel Agent Orchestration — Microsoft Learn](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-orchestration/)
- [CrewAI vs AutoGen comparison 2026 — OpenAgents Blog](https://openagents.org/blog/posts/2026-02-23-open-source-ai-agent-frameworks-compared)
- [Best Multi-Agent Frameworks 2026 — gurusup.com](https://gurusup.com/blog/best-multi-agent-frameworks-2026)

**Claude Code Ecosystem**
- [Claude Code custom subagents docs](https://code.claude.com/docs/en/sub-agents)
- [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
- [Claude Code agent teams](https://code.claude.com/docs/en/agent-teams)
- [Claude Code hooks guide — DataCamp](https://www.datacamp.com/tutorial/claude-code-hooks)
- [Claude Code hooks — all 12 events 2026](https://www.pixelmojo.io/blogs/claude-code-hooks-production-quality-ci-cd-patterns)
- [Claude Octopus plugin — GitHub](https://github.com/nyldn/claude-octopus)
- [Building agents with Claude Agent SDK — Anthropic Engineering](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)

**Search and Retrieval**
- [Exa vs Tavily vs Serper vs Brave for AI agents — DEV Community](https://dev.to/supertrained/exa-vs-tavily-vs-serper-vs-brave-search-for-ai-agents-an-score-comparison-2l1g)
- [Agentic Search 2026: Benchmark 8 APIs — AI Multiple](https://aimultiple.com/agentic-search)
- [5 Best Deep Research APIs for Agentic Workflows 2026 — Firecrawl](https://www.firecrawl.dev/blog/best-deep-research-apis)
- [In-depth evaluation of top 5 MCP search tools 2025 — Oreate AI](https://www.oreateai.com/blog/indepth-evaluation-of-the-top-5-popular-mcp-search-tools-in-2025-technical-analysis-and-developer-selection-guide-for-exa-brave-tavily-duckduckgo-and-perplexity/3badf1e2e4f4177c0a04d075c34186e3)

**Synthesis and Evaluation**
- [Leveraging LLMs as Meta-Judges — arxiv 2504.17087](https://arxiv.org/html/2504.17087v1)
- [Voting or Consensus? Decision-Making in Multi-Agent Debate — ACL 2025](https://aclanthology.org/2025.findings-acl.606/)
- [Multi-Agent Debate for LLM Judges with Adaptive Stability Detection — arxiv 2510.12697](https://arxiv.org/html/2510.12697v1)
- [Adversarial Multi-Agent Evaluation of LLMs through Iterative Debate — OpenReview](https://openreview.net/forum?id=06ZvHHBR0i)
- [Medical AI Consensus: Multi-Agent Framework — arxiv 2509.17353](https://arxiv.org/html/2509.17353)
- [Evaluation and Benchmarking of LLM Agents: A Survey — ACM KDD 2025](https://dl.acm.org/doi/10.1145/3711896.3736570)

**Cost Optimization**
- [AI Agent Cost Optimization: Token Economics — Zylos Research 2026](https://zylos.ai/research/2026-02-19-ai-agent-cost-optimization-token-economics)
- [LLM Token Optimization: Cut Costs & Latency 2026 — Redis](https://redis.io/blog/llm-token-optimization-speed-up-apps/)
- [Entropy-Guided KV Caching — MDPI Mathematics 2025](https://www.mdpi.com/2227-7390/13/15/2366)

**RAG and Memory**
- [Agentic RAG: A Survey — arxiv 2501.09136](https://arxiv.org/html/2501.09136v2)
- [A-RAG: Scaling Agentic RAG via Hierarchical Retrieval — arxiv 2602.03442](https://arxiv.org/html/2602.03442v1)

---

### Findings

**1. LangGraph's Send API enables true dynamic fan-out — interflux uses a static roster**

LangGraph's `Send` API (used in its orchestrator-worker pattern) dispatches variable numbers of worker nodes at runtime based on a planner's output, where each `Send("llm_call", {"section": s})` creates an independent parallel branch. The aggregator node waits for all branches before proceeding. This is structurally identical to interflux's Stage 1/Stage 2 dispatch, but LangGraph encodes the expansion graph explicitly as typed state, making retry, replay, and partial failure handling deterministic.

Interflux's current approach dispatches agents via the Agent tool with `run_in_background: true`, relying on the host Claude instance's context to track completion. The absence of a typed state graph means: (a) Stage 2 expansion scoring is computed in-prompt rather than from structured data, and (b) retry logic on agent failure must be re-implemented per run rather than being graph-level.

Applicable pattern: A lightweight structured agent-state log (JSONL per agent: `{name, status, stage, model, score, started_at, completed_at}`) would let the synthesis subagent compute convergence and dropout decisions from typed data rather than prose parsing. This is narrower than adopting LangGraph — it's capturing the typed-state discipline without the framework dependency.

Confidence: high

---

**2. Semantic Kernel's Magentic/Concurrent patterns validate interflux's two-stage architecture, but SK has first-class handoff logic interflux lacks**

Semantic Kernel formalizes five orchestration patterns: Sequential, Concurrent, Handoff, Group Chat, and Magentic. The Concurrent pattern (identical to interflux's Stage 1 parallel launch) and Magentic pattern (a manager agent dynamically assigns tasks and re-routes based on intermediate results) both map cleanly onto interflux's design. SK's notable addition over interflux is the Handoff pattern: agents can explicitly signal that another agent is better suited, transferring control mid-review. Interflux's equivalent — AgentDropout, which prunes redundant agents — is a passive elimination rather than active handoff.

Applicable pattern: A lightweight handoff signal in the findings JSONL format (`"handoff": {"to": "fd-safety", "reason": "race condition detected in auth layer"}`) would let Stage 1 agents dynamically request additional Stage 2 specialists rather than relying solely on the orchestrator's adjacency scoring. This would strengthen the expansion heuristic from score-based to evidence-based.

Confidence: medium (SK Magentic is newer, evidence for production effectiveness is limited)

---

**3. Multi-model dispatch is the highest-leverage architectural change not yet taken — competitors are already doing it**

Claude Octopus (a peer Claude Code plugin) dispatches up to 8 providers (Codex, Gemini, Perplexity, OpenRouter, Copilot, Qwen, Ollama) in parallel and applies a 75% consensus quality gate. It runs providers in parallel for research and adversarially for review. The plugin's stated rationale matches interflux's PHILOSOPHY.md conviction exactly: "different models have different blind spots, and cross-model disagreement is higher-signal than same-model agreement."

interflux's protocol spec acknowledges this: "Today interflux dispatches same-model subagents; the protocol and contracts are designed so cross-model dispatch is a configuration change, not an architecture change." The findings contract (Findings Index format, `.md.partial` sentinel, `findings.json`) is already model-agnostic.

The concrete gap is in the triage scoring system: the current domain_boost and base_score dimensions select agents but do not incorporate model-diversity as a selection signal. Dispatching two models on the same agent role (e.g., fd-safety on both Claude Sonnet and GPT-4o) would require a slot budget that accounts for model pairs rather than agent count.

Confidence: high

---

**4. Debate-then-vote improves quality over consensus, but adds token cost — the right place for it in interflux is selective adversarial synthesis, not full debate rounds**

ACL 2025 research (arxiv 2502.19130) found that voting protocols improve performance by 13.2% in reasoning tasks versus consensus. The primary risks are: (a) error propagation when incorrect agents influence correct ones during debate, and (b) significant token overhead from multiple rounds of inter-agent communication.

interflux already captures disagreement via the peer-findings.jsonl protocol, where agents share blocking/notable findings that others must acknowledge. The Lorenzen discourse game config (`config/flux-drive/discourse-lorenzen.yaml`) adds structured move-type validation to synthesis. The gap is that disagreements currently flow into synthesis but do not trigger a targeted second opinion. A "dispute resolution" pattern — where two agents with conflicting P0 findings are asked to read each other's full section and re-assess — could recover the value of debate without full multi-round overhead.

The medical consensus research (arxiv 2509.17353) validates a similar staged approach: parallel independent review → automated disagreement detection → targeted reconciliation pass, rather than upfront debate.

Confidence: medium

---

**5. Brave Search has overtaken Exa in agentic search benchmarks — interflux should evaluate it as a fallback**

Current benchmark data (aimultiple.com, 2026): Brave Search leads with a 14.89 score, consistently outperforming Tavily by ~1 point. Exa scores higher on semantic similarity searches and domain filtering (1,200 domain filters vs. Tavily's). Tavily was acquired by Nebius (February 2026) — future API stability is uncertain.

interflux's Exa MCP server is already a progressive enhancement: if `EXA_API_KEY` is unset, agents fall back to Context7 + WebSearch. The fallback chain should be documented more explicitly: Exa (semantic, best for document discovery) → Brave (independent index, best for recent news/current facts) → Tavily (ergonomic, agent-native structured output) → Context7 + WebSearch (always-available baseline).

An additional gap: Perplexity Sonar API returns LLM-generated answers with citations rather than raw search results. For research agents that need to synthesize external information rather than retrieve documents, Sonar would reduce the synthesis burden on the agent itself.

Confidence: high (benchmark data is current; Tavily acquisition is confirmed)

---

**6. Agentic RAG with hierarchical retrieval would improve interflux's knowledge injection step**

Current knowledge injection (Step 2.1): the orchestrator calls `mcp__plugin_interknow_qmd__vsearch` with a fixed limit of 5 entries per agent, using keyword + domain queries. This is flat vector search — it retrieves similar past findings but does not reason about which entries are most likely to prevent blind spots on this specific document.

The A-RAG framework (arxiv 2602.03442) shows that iterative hierarchical retrieval — keyword search → semantic search → chunk read — with agent-controlled termination outperforms fixed-limit flat retrieval. Applied to interflux: the knowledge injection step could issue a two-pass query: (1) broad semantic search for the agent's domain, (2) targeted keyword search for specific patterns identified in the document summary. The orchestrator already computes a document profile in Step 1 — this profile's key signals (file types, risky patterns, architecture changes) could drive second-pass knowledge queries.

Confidence: medium (A-RAG results are on knowledge-base tasks; transfer to review knowledge injection is plausible but not directly validated)

---

**7. PostToolUse hooks can deliver inter-agent findings without JSONL file polling**

Current peer-findings mechanism: agents write to `{OUTPUT_DIR}/peer-findings.jsonl` using `findings-helper.sh`, and other agents poll or read the file during their review. This requires filesystem coordination and creates a dependency on the shared filesystem being visible to all subagents.

Claude Code's `PostToolUse` hook (available since v2.1.9) can inject `additionalContext` into a tool's result that flows back into the agent's context. A PostToolUse hook on the `Agent` tool could intercept completed agent outputs and inject a compact peer-findings summary into the next agent's launch context before it reads the filesystem. This would eliminate the polling pattern and make inter-agent findings delivery more reliable when `OUTPUT_DIR` resolution varies between subagent contexts.

The PreToolUse hook on `Agent` can also modify the dispatched prompt (`updatedInput`) before subagent launch — useful for injecting late-arriving domain signals or budget overrides without re-generating the full dispatch block.

Confidence: medium (hook behavior with Agent tool specifically needs empirical testing)

---

**8. Token-level budgeting lacks KV cache awareness — prefix caching offers 40-90% reduction on repeated system prompts**

Current cost model: `scripts/estimate-costs.sh` queries interstat for historical per-agent token usage, falling back to `budget.yaml` defaults. The model estimates total tokens but does not account for Anthropic prefix caching, which delivers ~90% cost reduction on cached tokens ($0.30/M vs $3.00/M for cache reads vs. new input).

All 12 review agents share the same system prompt structure: frontmatter, domain criteria, knowledge context, and input document. The input document prefix is identical across all agents on the same run. If interflux pre-populates the cache by issuing a warm-up read of the document before dispatching agents, subsequent agents that receive the document in their context would benefit from cache hits. The budget model should track a `cache_eligible_tokens` field alongside `estimated_tokens` so the cost report accurately reflects expected billing after caching.

The ARKV adaptive KV cache research (arxiv 2603.08727) is not directly applicable to Claude Code's API surface, but the principle applies to interflux's architecture: agents that review the same document in the same session should share cached computation, and the cost accounting should reflect this.

Confidence: high (prefix caching is an Anthropic production feature; behavior with multi-subagent dispatch needs verification)

---

**9. Evaluation rubrics for multi-agent review quality are absent — interflux has no systematic way to measure whether reviews improve over time**

The ACM KDD 2025 survey of LLM agent evaluation identifies four evaluation objectives: behavior, capabilities, reliability, and safety. For multi-agent review systems specifically, the relevant metrics are: finding recall (did the system catch known issues?), finding precision (were flagged issues real?), convergence consistency (does the same input produce stable findings across runs?), and coverage breadth (which agent missed what?).

interflux currently tracks: token cost per agent (via interstat + cost_report in findings.json), agent verdict (safe/needs-changes/risky), and finding convergence counts. It does not track: recall against a known-issues baseline, precision against developer-confirmed resolutions, or per-agent coverage gaps over time.

The meta-judge framework (arxiv 2504.17087) applies a multi-dimensional weighted rubric to evaluate LLM-generated judgments. An analogous interflux "review health" score could weigh: P0/P1 finding density (more findings on the same document = useful), developer confirmation rate (findings that led to bead creation and resolution), and cross-agent agreement rate (calibrated — neither too high nor too low). This would make the compounding knowledge lifecycle measurable rather than latent.

Confidence: medium (the metric framework is well-grounded; implementing ground-truth labeling in the interflux workflow requires user-facing changes)

---

**10. CrewAI's hierarchical manager agent and AutoGen's GroupChat manager fill a gap in interflux's triage — the orchestrator itself is not an agent**

In CrewAI's hierarchical process, a manager agent is auto-generated to oversee task delegation and review outputs, aware of all specialist agents' capabilities. In AutoGen's GroupChat, a centralized Group Chat Manager (itself LLM-powered) selects the next speaker based on conversation context. Both frameworks treat the orchestrator as a first-class agent that reasons about the team's composition and progress.

interflux's triage (Phase 1) is implemented as a series of scoring steps executed by the host Claude instance — the same instance that will later synthesize. The orchestrator does not have a separate persona, memory, or tool surface; it is the host agent reading the SKILL.md protocol. This conflates the orchestrator role with the synthesis role, which means that host context consumption from triage also affects synthesis context.

Applicable pattern: A lightweight "triage subagent" that executes Steps 1.0–1.2 independently and returns a structured roster JSON would offload domain classification, score computation, and slot ceiling calculation from the host context. The host would only receive the approved roster and proceed to dispatch. This matches the interflux vision's "contracts beat clever prompts" conviction — the triage output becomes a typed artifact rather than in-context state.

Confidence: medium (architectural; would require SKILL.md restructuring and may increase latency from subagent round-trip)

---

### Confidence

| Finding | Confidence | Basis |
|---------|------------|-------|
| 1 — Typed agent-state log pattern from LangGraph | high | Official LangGraph docs; pattern is directly applicable |
| 2 — Handoff signal from SK Magentic pattern | medium | SK pattern documented; production effectiveness of Magentic is early |
| 3 — Multi-model dispatch gap | high | Claude Octopus confirms pattern viability; interflux protocol spec explicitly defers it |
| 4 — Selective adversarial synthesis over full debate | medium | ACL 2025 paper confirms debate ROI; selective application is inferred |
| 5 — Brave Search as Exa fallback | high | Current benchmark data; Tavily acquisition confirmed |
| 6 — Hierarchical retrieval for knowledge injection | medium | A-RAG paper is strong; transfer to review knowledge is inferred |
| 7 — PostToolUse for inter-agent findings | medium | Hook capability is documented; Agent tool interaction needs empirical testing |
| 8 — KV cache awareness in budget model | high | Anthropic prefix caching is production; multi-subagent behavior needs verification |
| 9 — Evaluation rubrics gap | medium | KDD 2025 survey is authoritative; implementation path requires user-facing changes |
| 10 — Triage subagent delegation | medium | Framework analogy is sound; latency tradeoff needs measurement |

---

### Gaps

**What could not be determined from available sources:**

1. **Prefix cache behavior with parallel subagents**: It is unclear whether multiple concurrent subagents dispatched in the same Claude Code session share prefix cache entries or each pay full input costs. Anthropic's caching documentation describes per-request caching but does not specify subagent isolation behavior. Empirical measurement via interstat is needed.

2. **PostToolUse hook interaction with the Agent tool specifically**: The hooks reference documents PostToolUse for Bash, Edit, Write, etc., but the behavior when the matched tool is `Agent` (subagent dispatch) — and specifically whether `additionalContext` from a PostToolUse hook is visible to the next Agent tool call in the same session — is not clearly documented.

3. **Lorenzen discourse game validation results**: The `discourse-lorenzen.yaml` config referenced in `synthesize.md` defines move types and legality scoring, but no research output was found validating whether the Lorenzen dialogue game structure measurably improves synthesis quality over ad-hoc deduplication. The gap between defining the structure and measuring its effect is open.

4. **Firecrawl vs. Exa for JavaScript-heavy documentation sites**: Firecrawl handles SPAs and authenticated content via browser-based scraping, which Exa's crawler may not do reliably. For the `framework-docs-researcher` agent in particular — which targets official library docs that are often React/Next.js SPAs — it is unclear whether Exa's document retrieval degrades on those targets versus Firecrawl.

5. **Multi-model dispatch latency overhead**: Claude Octopus claims 3-5x speedup from parallelism in oh-my-claudecode benchmarks, but no controlled study of the latency impact of dispatching two models on the same agent role (vs. one) was found. The net latency effect depends on whether the parallel dispatch overhead is additive or whether the faster model's result can be used as an early signal.

6. **Interoperability between flux-drive-spec and LangGraph/SK**: The flux-drive protocol spec (`docs/spec/`) is described as framework-agnostic. It is unknown whether any external implementors have attempted to conform to it, or whether the spec's completion signal (`.md.partial` rename) is compatible with LangGraph's checkpoint/state persistence model.

<!-- flux-research:complete -->
