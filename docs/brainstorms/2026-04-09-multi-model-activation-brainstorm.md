---
artifact_type: brainstorm
bead: sylveste-fyo3
stage: discover
---

# Multi-Model Activation — Brainstorm

## What We're Building

A closed-loop pipeline that discovers, qualifies, and dispatches non-Claude models into flux-drive reviews via an OpenRouter MCP proxy. The goal is co-primary cost reduction and finding diversity, with provider resilience as a tertiary hedge.

The pipeline: interrank discovers candidates → FluxBench qualifies them against ground-truth fixtures → qualified models dispatch through an MCP tool into real reviews → drift detection monitors ongoing performance → challenger slot evaluates newcomers.

All non-safety tiers are eligible for non-Claude dispatch (everything except fd-safety and fd-correctness, which are locked to Sonnet+). Safety is ensured through four mitigations: convergence guard, rolling qualification, shadow-then-enforce per tier, and Stage 2 before Stage 1.

## Why This Approach

**MCP proxy for transport.** The Agent tool only accepts `model:` (Claude tiers). Non-Claude dispatch requires an alternate channel. An MCP server with a `review_with_model` tool is the cleanest integration — the flux-drive skill calls it alongside Agent tool invocations, and findings merge into the same synthesis pipeline. No Claude Code platform changes required.

**Interrank for discovery.** The recommend_model and cost_leaderboard MCP tools already exist. Budget.yaml has per-tier task_queries ready. Let interrank's Pareto-efficient scoring pick candidates rather than hardcoding model choices — this decouples model selection from the pipeline, so new models enter automatically.

**Thin vertical slice sequencing.** Build the minimum viable path end-to-end before broadening: OpenRouter MCP → real qualify (one model) → single discovery run → enforce mode (one tier) → ship first non-Claude review. Measure cost and convergence before scaling.

## Key Decisions

1. **Transport: MCP proxy, not Agent tool** — OpenRouter MCP server exposes `review_with_model(prompt, model_slug, provider)` → returns findings JSON. flux-drive skill dispatches via this tool for non-Claude models, via Agent tool for Claude models.

2. **Goals: cost + diversity co-primary** — Cost reduction targets 20%+ per-review spend. Diversity measured by cross-family convergence on P0/P1 findings (Claude + non-Claude agreement). Provider resilience is a bonus, not a gate.

3. **Eligible tiers: all except safety floors** — Any non-safety agent can dispatch to a qualified non-Claude model. fd-safety and fd-correctness locked to Claude Sonnet+. Eligibility is per-model (each model declares its `eligible_tiers` in the registry).

4. **Four mitigations for broad eligibility:**
   - Convergence guard: require at least one Claude agent per stage. Single-source P0/P1 from non-Claude gets `verification_recommended: true`.
   - Rolling qualification: FluxBench drift samples every Nth dispatch (sample_rate=10). Regression >15% → auto-demote.
   - Shadow-then-enforce per tier: 20 shadow runs (parallel with Claude) per tier before enforce mode. Convergence >= 85% required.
   - Stage asymmetry: non-Claude enters Stage 2 first. Stage 1 only after 50+ successful Stage 2 runs.

5. **Model selection: interrank-driven** — Don't pre-commit to specific models. Let the first real discovery run query interrank for Pareto-efficient candidates per tier (checker, analytical, judgment). Models earn their way in through qualification.

6. **Sequencing: thin vertical slice first** — OpenRouter MCP → real qualify → single discovery → enforce one tier → ship. Then expand to challenger wiring, fleet drift, calibration, and automation.

7. **Success criteria (three sequential checkpoints):**
   - First non-Claude review ships (findings merged into synthesis)
   - Cost reduction measurable (20%+ after 10+ reviews)
   - Cross-family convergence observed (5+ reviews with Claude + non-Claude agreeing on P0/P1)

## Open Questions

- **OpenRouter rate limits:** Free tier is 20 req/min. A flux-drive run with 3 non-Claude agents dispatched simultaneously could hit this. Should the MCP proxy queue internally, or should triage cap non-Claude slots?
- **Prompt compatibility:** Agent tool prompts include Claude-specific instructions (artifact format, XML tags). Non-Claude models may interpret these differently. Need a prompt normalization layer in the MCP proxy?
- **Cost tracking:** interstat tracks Claude tokens natively. OpenRouter responses will need separate cost accounting (different token pricing). Where does this merge — in estimate-costs.sh, in interstat, or in the MCP proxy itself?
- **Latency budget:** Non-Claude models via OpenRouter add network hops. Should the triage scoring factor in expected latency, or just cap total review wall-clock time?
