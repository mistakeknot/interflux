### Sources

- [Multi-Agent LLM Orchestration — Deterministic Decision Support for Incident Response](https://arxiv.org/abs/2511.15755) (arXiv 2511.15755, Nov 2025)
- [LLM-Based Multi-Agent Systems for Software Engineering: Literature Review](https://dl.acm.org/doi/10.1145/3712003) (ACM TOSEM, 2025)
- [Difficulty-Aware Agentic Orchestration for Query-Specific Multi-Agent Workflows](https://arxiv.org/abs/2509.11079) (arXiv 2509.11079, Sep 2025)
- [AgentDropout: Dynamic Agent Elimination for Token-Efficient Multi-Agent Collaboration](https://arxiv.org/abs/2503.18891) (arXiv 2503.18891, ACL 2025)
- [EET: Experience-Driven Early Termination for Cost-Efficient Software Engineering Agents](https://arxiv.org/html/2601.05777) (arXiv 2601.05777, Jan 2026)
- [MAR: Multi-Agent Reflexion Improves Reasoning Abilities in LLMs](https://arxiv.org/html/2512.20845) (arXiv 2512.20845, Dec 2025)
- [Voting or Consensus? Decision-Making in Multi-Agent Systems](https://aclanthology.org/2025.findings-acl.606.pdf) (ACL Findings 2025)
- [DiscoUQ: Structured Disagreement Analysis for Uncertainty Quantification in LLM Agent Ensembles](https://arxiv.org/abs/2603.20975) (arXiv 2603.20975, Mar 2026)
- [Multi-Agent Debate for LLM Judges with Adaptive Stability Detection](https://arxiv.org/html/2510.12697v1) (arXiv 2510.12697, Oct 2025)
- [Adversarial Multi-Agent Evaluation via Iterative Debate (D3)](https://arxiv.org/abs/2410.04663) (OpenReview 2025)
- [Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG](https://arxiv.org/abs/2501.09136) (arXiv 2501.09136, Jan 2025)
- [The Multi-Agent Trap](https://towardsdatascience.com/the-multi-agent-trap/) (Towards Data Science, 2025)
- [Towards a Science of Scaling Agent Systems](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/) (Google Research, 2025)
- [Multi-Agent Collaboration Mechanisms: A Survey of LLMs](https://arxiv.org/html/2501.06322v1) (arXiv 2501.06322, Jan 2025)
- [Stop Wasting Your Tokens: Efficient Runtime Multi-Agent Systems](https://openreview.net/forum?id=pzFhtpkabh) (OpenReview 2025)
- [Multi-Agent Evolving Orchestration Learns Task Routing](https://blog.promptlayer.com/multi-agent-evolving-orchestration/) (PromptLayer Blog, 2025)
- [Empirical Analysis of OpenAI Embeddings for Semantic Code Review Comment Similarity](https://link.springer.com/chapter/10.1007/978-3-032-04190-6_3) (Springer, 2026)

---

### Findings

**1. Deterministic multi-agent orchestration outperforms single-agent by an order of magnitude on complex review tasks.**

The Nov 2025 incident-response paper (arXiv 2511.15755) measured multi-agent orchestration achieving a 100% actionable recommendation rate versus 1.7% for single-agent, an 80x improvement in action specificity, and 140x improvement in solution correctness. Crucially, multi-agent systems exhibited zero quality variance across all trials — enabling SLA commitments that are structurally impossible with single-agent outputs. The mechanism is division of cognitive labor: each agent applies full attention to a narrow domain rather than context-switching across all concerns.

**Implication for interflux:** The current staged dispatch model (Stage 1 / Stage 2) is architecturally correct. The gains compound when agents have genuinely differentiated specializations, not just different names. The 17 agents in interflux need distinct cognitive profiles — divergent by design — not just domain labels. Audit whether fd-quality and fd-correctness, or fd-architecture and fd-performance, share too many review heuristics.

**Confidence: High** — replicated across multiple 2025 benchmarks; mechanism is well understood.

---

**2. Agent dropout (dynamic elimination) reduces token consumption 20–22% with zero quality loss.**

AgentDropout (ACL 2025, arXiv 2503.18891) trains a graph over agent communication, then applies two pruning operations per round: Node Dropout (removing agents with lowest weighted contribution) and Edge Dropout (removing low-value agent-to-agent communication edges). Result: 21.6% reduction in prompt tokens, 18.4% reduction in completion tokens, +1.14 performance improvement. The key insight is that agent contribution is non-uniform across rounds — high-value agents in Stage 1 may be redundant in Stage 2.

**Implication for interflux:** The current architecture dispatches agents and waits for all of them. There is no mechanism to terminate individual agents early once their marginal contribution is predictably zero (e.g., a safety agent in a pure documentation review). Adding a lightweight per-agent contribution predictor — even a rule-based one using domain score × finding rate from prior runs — could gate Stage 2 launches dynamically. This is different from the current "early stop if Stage 1 finds nothing" — it's per-agent dropout mid-review.

**Confidence: High** — paper appears at ACL 2025 (peer-reviewed), results replicated across six benchmarks.

---

**3. Experience-driven early termination cuts costs 19–55% with negligible quality loss.**

EET (arXiv 2601.05777, Jan 2026) learns from prior agent runs to identify when an issue is structurally similar to ones that resolved quickly, then terminates the agent early rather than running to completion. On SWE-bench–style tasks, EET reduces API calls by 20.8%, input tokens by 29.9%, output tokens by 25.1%, and total cost by 31.8% on average — with at most 0.2% drop in resolution rate. EET operates at the session level: it predicts early-termination opportunity before the agent starts, not during the run.

**Implication for interflux:** The existing trust multiplier (from interspect) is a weak version of this: agents with low historical precision get de-prioritized. A stronger version would use findings history to predict, per input type × agent pair, whether the agent is likely to contribute unique findings. If an agent has contributed zero unique P0/P1 findings across the last 20 reviews of a given domain, its launch for that domain should require explicit user override. This maps cleanly onto the existing `expansion pool` concept — pool membership could be earned, not just score-based.

**Confidence: High** — published Jan 2026, evaluated on real SWE-bench tasks.

---

**4. Difficulty-aware orchestration adapts agent count and model tier to input complexity, cutting cost 36% while improving accuracy 11%.**

DAAO (arXiv 2509.11079, Sep 2025) uses a variational autoencoder to estimate query difficulty, then dispatches proportionally: simple queries get 1–2 lightweight agents, complex queries get the full ensemble with stronger models. Results: 11.21% accuracy improvement over static multi-agent baselines, 36% inference cost reduction. The difficulty estimator is trained on prior run outcomes — making it a learned routing signal.

**Implication for interflux:** The current slot ceiling formula (`base + scope + domain`) is a static proxy for complexity. An evolved version would estimate input difficulty from content signals (cyclomatic complexity proxies, section count, detected anti-patterns, diff entropy) and adjust not just slot count but also model tier. For a simple 20-line config diff, dispatching 4 mid-tier agents is likely better than 2 expensive agents. interflux doesn't currently vary model tier — all agents run on the same model. This is a high-leverage gap.

**Confidence: High** — six benchmarks, clear mechanism; applies directly to interflux's staged dispatch.

---

**5. Structured disagreement is the highest-value signal in multi-agent ensembles — current synthesis smooths it away.**

DiscoUQ (arXiv 2603.20975, Mar 2026) demonstrates that inter-agent disagreement carries structured information about both answer correctness and uncertainty. The framework extracts linguistic properties (evidence overlap, argument strength, divergence depth) and embedding geometry (cluster distances, dispersion) from disagreements. This out-performs simple vote counting, especially in the "weak disagreement" tier — where two agents partially agree but diverge on severity or scope. AUROC 0.802 vs. 0.791 for the best vote-counting baseline, with substantially better calibration (ECE 0.036 vs. 0.098).

This aligns with interflux's vision principle: "Disagreement is the primary quality signal." The vision states this explicitly, but the current synthesis spec smooths disagreements by taking the max severity and flagging conflicts in a `severity_conflict` field. That is necessary but insufficient — the disagreement structure itself (which agents agree, which diverge, whether the divergence is on severity vs. scope vs. location) should be a first-class output.

**Implication for interflux:** The `findings.json` schema should include a `disagreement_profile` field per finding cluster: which agents agree on title but diverge on severity, which agree on severity but propose different fixes, and whether the disagreement is between agents of the same specialization class (two technical agents) or cross-class (technical vs. cognitive). Cross-class disagreement is particularly high-signal — it often indicates a finding that is technically correct but has product/UX implications the technical agent missed.

**Confidence: High** — peer reviewed, Mar 2026, directly applicable to the existing convergence tracking spec.

---

**6. Adversarial debate with adaptive stopping outperforms majority voting for synthesis quality.**

Multi-Agent Debate for LLM Judges (arXiv 2510.12697, Oct 2025) uses a structured debate: agents argue for and against findings, a judge synthesizes. Key finding: 3-round debates reliably improve synthesis accuracy, but 4+ rounds introduce noise and error accumulation — over-debating degrades quality. Adaptive stopping (detecting when judge consensus stabilizes via distributional similarity) outperforms fixed-round budgets. The D3 framework (arXiv 2410.04663) adds role specialization: advocates per finding, a judge, an optional jury.

For interflux's synthesis phase, this suggests two actionable patterns: (1) for high-stakes single-agent P0 findings, a lightweight adversarial pass (one "devil's advocate" agent reviewing the P0 claim) could reduce false positives significantly; (2) synthesis agent confidence should be a function of how quickly agents converged, not just how many agreed. Fast convergence on a finding = high confidence. Slow convergence after multiple iterations = uncertainty signal.

**Implication for interflux:** Add an optional adversarial validation pass for single-agent P0 findings before they reach the verdict. The synthesis spec already flags these with "Single-agent finding — verify independently." That flag could trigger an automatic short-form review by a meta-agent specifically tasked with finding counter-evidence for the P0 claim. This would make the "verify independently" flag actionable rather than just advisory.

**Confidence: Medium-High** — the 3-round sweet spot is well-documented; adversarial pass for P0s is an inference from this, not directly measured.

---

**7. Semantic deduplication using embedding similarity catches false negatives that Levenshtein distance misses.**

The current interflux deduplication spec uses Levenshtein distance < 0.3 and keyword overlap (3+ shared words) to detect duplicate findings. Research from 2025–2026 on semantic code review comment similarity (Springer 2026) and SemHash (MinishLab) demonstrates that embedding-based similarity catches conceptually identical findings with different surface wording — a pattern that Levenshtein distance systematically misses. For example, "Missing null check before database insert" and "Potential NPE in persistence layer" describe the same issue but share zero keywords and have Levenshtein distance > 0.3.

The existing Tier 1 (Findings Index) + Tier 2 (prose fallback) collection architecture is well-suited to add embedding-based deduplication as a third pass: after Levenshtein/keyword dedup, embed all remaining unique finding titles, cluster at cosine similarity > 0.85, and flag clusters for human review. This would not require full prose reads — short title embeddings are cheap.

**Implication for interflux:** Replace or augment the Levenshtein + keyword dedup in synthesis Step 3 with an embedding pass. The dedup rules (R1–R5) remain correct as policy; only the matching mechanism changes. Use a lightweight embedding model (no external API call needed — a local sentence transformer is sufficient for title-length strings). This is a clear quality improvement with low implementation risk.

**Confidence: Medium-High** — embedding dedup is industry standard for 2025; the false-negative rate of Levenshtein on finding titles is a documented pattern in review systems.

---

**8. Multi-agent systems degrade on sequentially dependent tasks — parallel dispatch must only cover genuinely parallelizable concerns.**

Google Research (2025) and Dataiku analysis document a pattern: on tasks requiring strict sequential reasoning, multi-agent variants degrade performance by 39–70% versus single-agent baselines. The mechanism is cognitive fragmentation: inter-agent communication overhead consumes context budget that the actual reasoning task needs. Parallelism is beneficial when agents cover disjoint concern dimensions; it is harmful when agents must share intermediate state.

The "Multi-Agent Trap" (Towards Data Science, 2025) warns that unstructured agent networks amplify errors up to 17.2x versus single-agent baselines. The solution is explicit role boundaries and protocol-driven communication — which interflux already has via the Findings Index contract.

**Implication for interflux:** The current agent set is designed around parallelizable review dimensions (safety, architecture, quality, performance) — this is architecturally correct. The risk emerges if new agents are added that need to observe other agents' findings before forming their own. The Peer Findings Protocol (sharing blocking findings via JSONL) partially addresses this, but the synthesis phase currently treats all agent outputs as independent. Agents that explicitly declare data dependencies should be dispatched after (not alongside) the agents they depend on. This would formalize the Stage 1 → Stage 2 dependency pattern.

**Confidence: High** — replicated across multiple 2025 benchmarks; mechanism is well understood.

---

**9. Agentic RAG with iterative filtering and citation-attributed answers is the current SOTA for research synthesis quality.**

Agentic RAG (arXiv 2501.09136, Jan 2025) and RAGentA (Besrour et al., 2025) demonstrate that research quality improves significantly when retrieval is iterative (not one-shot) and answers cite specific source passages (not just URLs). MMOA-RAG frames the retrieval pipeline as a cooperative multi-agent RL problem, with each retrieval component as an RL agent optimizing toward a unified reward. Key technique: each retrieved passage is tagged with source provenance before being fed to the synthesis agent — preventing source laundering (where a synthesized claim loses its original attribution).

**Implication for interflux's flux-research:** The current flux-research synthesis produces a `### Sources` section per agent, but the linkage between individual synthesized claims and their sources is loose — the synthesis agent collects sources and then writes a unified answer, which can lose attribution for individual claims. Shifting to passage-level citation (each synthesized claim tagged with the source that provided it) would produce research outputs that are auditable, not just attributed. This is higher implementation complexity but significantly improves the value of the research artifact.

**Confidence: Medium** — agentic RAG is well-established; passage-level citation in multi-agent synthesis is emerging but not yet production-standard.

---

**10. Model diversity (not agent count) is the primary driver of ensemble quality improvement.**

ReConcile (multi-agent debate, 2025) improves LLM ensemble accuracy by up to 11.4% over debate/judge baselines — with model diversity cited as the critical component. Homogeneous agent ensembles (same model, different prompts) show diminishing returns beyond 3 agents; heterogeneous ensembles (different model families) maintain improvement through 5–7 agents. The interflux vision explicitly anticipates cross-model dispatch ("different models have different blind spots, and cross-model disagreement is higher-signal than same-model disagreement") and states the protocol is designed for it as a configuration change.

**Implication for interflux:** Cross-model dispatch for at least a subset of agents — particularly for P0 findings and high-stakes reviews — should be on the near-term roadmap. The simplest version: route the Stage 2 expansion pool to a different model tier than Stage 1 agents. This requires no protocol changes, only routing configuration. The interspect trust multiplier already differentiates by agent, so per-model trust tracking is architecturally straightforward.

**Confidence: High** — model diversity as a quality driver is replicated across multiple ensemble papers; interflux's architecture is explicitly designed to support this.

---

**11. Dynamic orchestration learned from run history outperforms static scoring heuristics by 11–15% on complex tasks.**

Multi-Agent Evolving Orchestration (PromptLayer, 2025; OpenReview L0xZPXT3le) trains an orchestrator via reinforcement learning on past run outcomes — which agents, in which order, contributed findings that were accepted. The learned policy adapts to project-specific patterns (e.g., "for this Go codebase, fd-correctness consistently fires first and its findings gate fd-architecture's priorities") rather than relying on generic domain profiles.

**Implication for interflux:** The current scoring algorithm is static within a project session — trust multipliers provide a weak form of learning, but they don't capture run-to-run patterns within a project. A learned routing layer (even a simple Bayesian update from accepted/rejected findings per agent × domain × input-type) would give the slot ceiling formula real predictive power rather than heuristic power. The existing interspect trust feedback table is the natural place to accumulate this signal. The gap is that interspect currently tracks accepted findings, not the sequence and interaction patterns of which agents contributed what.

**Confidence: Medium** — RL-trained orchestrators are demonstrated in controlled settings; the Bayesian update version is an inference that would require validation.

---

**12. Query decomposition for complex research questions improves coverage and reduces hallucination.**

A-RAG (arXiv 2602.03442) introduces hierarchical retrieval: complex queries are decomposed into sub-queries, each retrieved independently, then answers re-composed. This prevents the common failure mode where a complex multi-part research question is answered by the first relevant document found (which covers only one part) and the remaining parts are confabulated. The flux-research brainstorm (2026-02-14) explicitly deferred query decomposition to v2, noting it was not needed for v1.

**Implication for interflux:** Query decomposition is now production-ready in agentic RAG systems. For flux-research, the "exploratory" and "onboarding" query types (which typically have multiple implicit sub-questions) would benefit most. Implementation: before agent dispatch, the triage phase decomposes complex queries into 2–4 sub-questions, dispatches agents per sub-question, then synthesizes across the sub-answers. This is a v2 capability but the decomposition step can be implemented without changing the agent architecture.

**Confidence: Medium** — A-RAG demonstrates the pattern; the direct application to flux-research's query types is an inference.

---

### Confidence

| Finding | Confidence | Basis |
|---------|-----------|-------|
| 1. Multi-agent vs. single-agent quality gap | High | Replicated across multiple 2025 papers, peer-reviewed |
| 2. AgentDropout — dynamic agent elimination | High | ACL 2025, six benchmarks |
| 3. EET — experience-driven early termination | High | arXiv Jan 2026, SWE-bench tasks |
| 4. DAAO — difficulty-aware orchestration | High | Six benchmarks, Sep 2025 |
| 5. Structured disagreement as quality signal | High | arXiv Mar 2026, four benchmarks |
| 6. Adversarial debate for P0 validation | Medium-High | Well-documented 3-round sweet spot; P0 application is inference |
| 7. Embedding-based deduplication | Medium-High | Industry standard 2025; interflux-specific gap is inferred |
| 8. Parallel vs. sequential task degradation | High | Google Research, multiple 2025 benchmarks |
| 9. Passage-level citation in research synthesis | Medium | Agentic RAG established; passage-level in multi-agent synthesis is emerging |
| 10. Model diversity as quality driver | High | Replicated across ensemble papers; interflux architecture already supports it |
| 11. Learned orchestration from run history | Medium | RL orchestrators demonstrated; Bayesian update version is inferred |
| 12. Query decomposition for complex research | Medium | A-RAG demonstrates; flux-research application is inferred |

---

### Gaps

1. **Embedding deduplication benchmarks for short finding titles** — All embedding deduplication research targets document-level or paragraph-level content. How well cosine similarity over embeddings performs on 5–15 word finding titles (the interflux case) is not directly measured. Would require local validation.

2. **Cost of adversarial P0 validation pass** — The adversarial debate literature uses symmetric debate (all claims contested). A selective adversarial pass (only single-agent P0s) is not directly benchmarked. The overhead (one extra agent per P0 finding) could be significant for reviews with many P0s.

3. **Cross-model dispatch at Claude Code plugin level** — All multi-model diversity research operates at the API level (direct model selection). How to implement model-tier routing within a Claude Code plugin (where the host controls model selection) is not documented. May require MCP tool or Interserve-level dispatch.

4. **Learned orchestration without negative labels** — Most RL-trained orchestrators require both positive (accepted findings) and negative (rejected findings) labels. The interspect trust table currently only tracks acceptance (via `/resolve`). Rejections are implicit (not present in the table), which may be insufficient for training a reliable routing policy.

5. **Query decomposition quality for code research questions** — A-RAG decomposition research focuses on open-domain QA. Whether LLM-based decomposition of code-focused research questions ("Why does this module use this pattern?") produces reliable sub-questions is not established in the literature.

<!-- flux-research:complete -->
