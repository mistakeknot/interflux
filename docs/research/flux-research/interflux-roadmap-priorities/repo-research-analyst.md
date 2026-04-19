### Sources

**Core documentation:**
- `/home/mk/projects/Sylveste/interverse/interflux/CLAUDE.md`
- `/home/mk/projects/Sylveste/interverse/interflux/AGENTS.md`
- `/home/mk/projects/Sylveste/interverse/interflux/PHILOSOPHY.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/interflux-vision.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/PRD.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/roadmap.md` (current: only 2 open items)

**Specification:**
- `/home/mk/projects/Sylveste/interverse/interflux/docs/spec/README.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/spec/core/protocol.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/spec/core/scoring.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/spec/core/staging.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/spec/core/synthesis.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/spec/contracts/findings-index.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/spec/extensions/knowledge-lifecycle.md`

**Skills and phases:**
- `/home/mk/projects/Sylveste/interverse/interflux/skills/flux-drive/SKILL.md`
- `/home/mk/projects/Sylveste/interverse/interflux/skills/flux-drive/phases/launch.md`
- `/home/mk/projects/Sylveste/interverse/interflux/skills/flux-drive/phases/synthesize.md`
- `/home/mk/projects/Sylveste/interverse/interflux/skills/flux-drive/phases/reaction.md`
- `/home/mk/projects/Sylveste/interverse/interflux/skills/flux-drive/phases/expansion.md`
- `/home/mk/projects/Sylveste/interverse/interflux/skills/flux-drive/phases/cross-ai.md`

**Commands:**
- `/home/mk/projects/Sylveste/interverse/interflux/commands/flux-drive.md`
- `/home/mk/projects/Sylveste/interverse/interflux/commands/flux-research.md`
- `/home/mk/projects/Sylveste/interverse/interflux/commands/flux-gen.md`
- `/home/mk/projects/Sylveste/interverse/interflux/commands/flux-explore.md`
- `/home/mk/projects/Sylveste/interverse/interflux/commands/flux-review.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/guide-choosing-flux-command.md`

**Agents (sampled):**
- `/home/mk/projects/Sylveste/interverse/interflux/agents/review/fd-architecture.md`
- `/home/mk/projects/Sylveste/interverse/interflux/agents/review/fd-systems.md`
- `/home/mk/projects/Sylveste/interverse/interflux/agents/review/fd-user-product.md`
- `/home/mk/projects/Sylveste/interverse/interflux/agents/research/best-practices-researcher.md`

**Configuration:**
- `/home/mk/projects/Sylveste/interverse/interflux/config/flux-drive/budget.yaml`
- `/home/mk/projects/Sylveste/interverse/interflux/config/flux-drive/agent-roles.yaml`
- `/home/mk/projects/Sylveste/interverse/interflux/config/flux-drive/reaction.yaml`
- `/home/mk/projects/Sylveste/interverse/interflux/config/flux-drive/discourse-topology.yaml`
- `/home/mk/projects/Sylveste/interverse/interflux/config/flux-drive/discourse-sawyer.yaml`
- `/home/mk/projects/Sylveste/interverse/interflux/config/flux-drive/discourse-lorenzen.yaml`
- `/home/mk/projects/Sylveste/interverse/interflux/config/flux-drive/knowledge/README.md`
- `/home/mk/projects/Sylveste/interverse/interflux/config/flux-drive/domains/` (index.yaml + 11 profiles)

**Brainstorms and plans:**
- `/home/mk/projects/Sylveste/interverse/interflux/docs/brainstorms/2026-02-14-flux-research-brainstorm.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/brainstorms/2026-02-22-flux-gen-precheck-brainstorm.md`

**Campaign artifacts:**
- `/home/mk/projects/Sylveste/interverse/interflux/campaigns/flux-review-token-efficiency/learnings.md`

**Plugin manifest:**
- `/home/mk/projects/Sylveste/interverse/interflux/.claude-plugin/plugin.json` (v0.2.56)

---

### Findings

**1. The roadmap is effectively empty — the system is more capable than its tracked work reflects.**

The current roadmap (`docs/roadmap.md`) lists only 2 open items: one P2 install bug and one P2 latent memory experiment. Meanwhile, the system has accumulated substantial capability across 6 commands (flux-drive, flux-research, flux-gen, flux-explore, flux-review, fetch-findings), a reaction round, discourse health protocols (Sawyer, Lorenzen, Fixative, Topology), AgentDropout, incremental expansion, cross-AI comparison, and trust multipliers. None of these recent additions have generated follow-on roadmap work, suggesting that post-completion retrospectives are not generating tracked improvements. The gap between the richness of the implementation and the emptiness of the roadmap is itself a signal: the project needs a systematic assessment cycle.

**2. The spec-to-implementation gap is a technical debt risk, particularly in spec v1.0.**

`docs/spec/README.md` describes flux-drive-spec 1.0.0 with 8 documents covering a 3-phase lifecycle. The spec was written to be framework-agnostic and claims to separate "what the protocol requires" from "what the implementation happens to do." However, several implementation features do not have corresponding spec coverage:

- The reaction round (Phase 2.5, with Lorenzen dialogue games, Sawyer health, Fixative injection, Topology filtering) has no spec document. This is a substantial protocol extension that any conformant implementation would need guidance on.
- The trust multiplier is documented in `scoring.md` but the feedback loop that populates it (interspect integration) has no spec contract.
- AgentDropout's empirical validation (26+ runs, 0% P0/P1 recall loss) supports a spec-level endorsement as a SHOULD requirement but is currently implementation-only.
- The intersynth delegation pattern (synthesis is delegated to a subagent, not done inline) has no spec coverage.

The spec was a significant investment and is the strongest differentiator for external adopters. Closing the gap between spec coverage and actual protocol features is high-impact for both external adoption and internal correctness.

**3. The synthesis pipeline has an implicit dependency on intersynth that is not documented as a formal integration contract.**

`phases/synthesize.md` Step 3.2 delegates ALL synthesis work (collection, deduplication, move validation, discourse health, verdict writing) to `intersynth:synthesize-review` and `intersynth:synthesize-research`. The host agent never reads individual agent output files. This is an important architectural decision — it keeps agent prose out of the host context — but intersynth is a separate plugin with its own lifecycle. There is no documented interface contract between interflux and intersynth: no schema for the expected prompt parameters, no versioning of the delegation protocol, and no graceful degradation behavior if intersynth is unavailable. If intersynth's synthesis agents change their behavior or the plugin is absent, flux-drive synthesis silently breaks.

**4. The discourse subsystem (reaction round + Lorenzen + Sawyer + Fixative + Topology) has grown complex enough to warrant its own testing and observability layer.**

The reaction round (`phases/reaction.md`) involves: convergence gate computation, intercept decision, topology-aware peer visibility filtering, fixative health injection, parallel reaction dispatch, sycophancy detection, hearsay rule, Lorenzen move validation, and Sawyer flow envelope monitoring. This is a 5-layer protocol operating on top of the base review cycle. The `discourse-health.sh` script provides post-hoc health output, but there is no:
- Test suite specifically for discourse dynamics (the structural tests cover agents/commands/skills/namespace/slicing, not discourse behavior)
- Observability dashboard or aggregated metrics across runs
- Documented failure modes (e.g., what happens when fixative fires on every reaction? What does topology isolation look like in practice?)
- Calibration guidance for the Sawyer thresholds (`participation_gini_max: 0.3`, `novelty_rate_min: 0.1`) — these are stated without empirical backing visible in the repo

**5. The campaigns/ directory contains validated learning that has not been institutionalized.**

`campaigns/flux-review-token-efficiency/learnings.md` documents 3 confirmed findings about token efficiency (inline examples waste, extract-and-reference beats inline, compression compounds). These learnings are not reflected in the AGENTS.md, PHILOSOPHY.md, or any guideline file. The pattern of "run a campaign, extract learnings, leave them in campaigns/" creates knowledge silos. There is also only one campaign, suggesting the campaign mechanism itself is underused relative to the volume of improvements made to the system.

**6. The flux-review command introduces a multi-track architecture that overlaps with but is independent of flux-drive's single-track architecture — the relationship is not formally specified.**

`flux-review` runs multiple parallel flux-drive instances (one per semantic distance track) and synthesizes across them. It is described in `guide-choosing-flux-command.md` as the "primary entry point." But the commands section in AGENTS.md still lists only 4 commands (flux-drive, flux-research, flux-gen, fetch-findings), and the PRD was last updated at v0.2.29 while the plugin is at v0.2.56. The flux-review and flux-explore commands are not covered in the PRD and have no spec-level documentation. Their relationship to the core protocol (do they extend flux-drive-spec? Are they a new conformance level?) is undefined.

**7. The domain coverage has a significant gap for AI/LLM-native projects.**

The 11 domain profiles are: `game-simulation`, `web-api`, `ml-pipeline`, `cli-tool`, `mobile-app`, `embedded-systems`, `data-pipeline`, `library-sdk`, `tui-app`, `desktop-tauri`, `claude-code-plugin`. The `claude-code-plugin` domain covers interflux's own use case, but there is no domain for:
- **AI agent systems** (multi-agent orchestration, LLM pipelines, prompt engineering systems) — broader than `claude-code-plugin`, which is specific to the Claude Code plugin format
- **devops/infra** — mentioned in `docs/spec/core/protocol.md` line 77-78 as a planned domain but not implemented in `config/flux-drive/domains/`
- **monorepo/platform engineering** — increasingly common, with its own patterns around module boundaries, dependency management, and cross-team contracts

The `ml-pipeline` domain partially covers AI use cases but focuses on data/training pipelines, not inference-time agent systems.

**8. The research synthesis path (intersynth delegation) is architecturally weaker than the review path.**

For review mode, interflux has a rich pre-synthesis pipeline: reaction round (Phase 2.5), discourse health monitoring, Lorenzen move validation, peer findings sharing, convergence gate, and sycophancy detection. For research mode, agents write to `{OUTPUT_DIR}/{agent-name}.md.partial`, flag with `<!-- flux-research:complete -->`, and then synthesis is entirely delegated to `intersynth:synthesize-research`. There is no equivalent of:
- Intermediate finding sharing between research agents (peer-findings.jsonl is review-only)
- Cross-agent research synthesis quality signals (Sawyer/Lorenzen have no research equivalent)
- Source authority ranking during parallel dispatch (only at synthesis time)
- Domain-aware research directives actually informing synthesis strategy (they shape agent queries but not how synthesis weights sources)

The asymmetry means research quality is entirely dependent on intersynth's synthesis agent, with no interflux-side quality mechanisms.

**9. The agent trust model has one-way signal flow: feedback goes from interspect to interflux, but interflux findings don't feed back to improve agent prompts.**

Trust multipliers (loaded from interspect via `lib-trust.sh`) adjust triage scores for agents with poor historical precision. This is a routing optimization: low-trust agents get lower scores and may not be selected. But the system has no mechanism for:
- Identifying WHY an agent has low trust (false positive patterns, domain mismatch, prompt ambiguity)
- Feeding that diagnosis back into agent prompt improvements
- Distinguishing between "agent is bad at this domain" vs "agent was bad at this project"
- Recovering agent trust after prompt improvements

The trust multiplier prevents dispatching bad agents but does not heal them. Combined with the observation that project-generated agents produce 0% P0/P1 findings (from `staging.md` empirical validation), there is a clear signal that generated agents need improvement feedback loops.

**10. The spec's knowledge lifecycle extension has a practical implementation gap: decay checking requires querying "10 reviews" but interflux has no counter for reviews per project.**

The knowledge-lifecycle spec says entries decay after "10 reviews (10 flux-drive runs on the same project where the entry was injected into at least one agent's context)." The compounding agent in `synthesize.md` handles provenance-based `lastConfirmed` updates but there is no mechanism for counting how many reviews have occurred per project where a knowledge entry was injected. Without this counter, temporal decay either doesn't happen (entries live forever) or is approximated by date (">60 days" as mentioned in AGENTS.md). This approximation can archive entries from projects with infrequent reviews even if only 2-3 reviews have occurred, and keep entries from high-frequency projects far past the 10-review threshold.

**11. The flux-gen domain mode and prompt mode agents persist indefinitely with no lifecycle management.**

`flux-gen` generates agents to `.claude/agents/fd-*.md`. These agents accumulate across runs: `--mode=skip-existing` means older agents from outdated domain detections survive indefinitely unless the user explicitly regenerates. There is no:
- Agent age tracking (when was this agent last regenerated?)
- Stale agent detection (domain profile changed but agent wasn't updated)
- Versioning of generated agents against `flux_gen_version` (the `agent-roles.yaml` mentions this but the enforcement is `--mode=regenerate-stale` which requires user intent)
- Cleanup mechanism for generated agents from projects that no longer exist

The `test_generate_agents.py` test suite validates generation but not lifecycle.

**12. The SKILL.md orchestration is procedural, not declarative — adding new phases or reconfiguring the pipeline requires modifying the skill file directly.**

The triage → launch → synthesize pipeline is expressed as sequential prose instructions across multiple phase files. Adding a new phase (e.g., a verification round after synthesis) requires editing `SKILL.md` and creating new phase files. There is no configuration layer between the SKILL.md instructions and the underlying phase implementations. The `budget.yaml`, `reaction.yaml`, and `discourse-*.yaml` files provide some configurability (toggle features on/off, adjust thresholds), but pipeline structure itself is hardcoded. This limits:
- The ability to selectively apply phases (e.g., reaction round without full review)
- Third-party extensions that want to insert steps between existing phases
- CI/CD mode configuration (the `mode_overrides.quality-gates: false` in reaction.yaml is a workaround, not a principled CI mode)

**13. The compact skill variant (SKILL-compact.md) is described in AGENTS.md as a "single-file version" but its maintenance discipline is unclear.**

`SKILL-compact.md` (15K) is loaded instead of the multi-file SKILL.md when `.skill-compact-manifest.json` exists. Both must implement the same triage algorithm. Given that the full SKILL.md and its phase files have seen significant changes (reaction round, expansion.md split out, flux-review integration), the compact variant likely drifts from the canonical. There is no test that compares behavior equivalence between compact and full variants, and the testing docs do not mention compact variant validation.

**14. The research agent roster has no domain-specific specialist agents for the most valuable use cases.**

The 5 research agents (`best-practices-researcher`, `framework-docs-researcher`, `git-history-analyzer`, `learnings-researcher`, `repo-research-analyst`) are domain-general. The flux-research brainstorm explicitly notes that domain-aware research is qualitatively better (domain-specific search terms produce "radically different and better results"). But unlike flux-gen which can create domain-specific review agents on demand, there is no equivalent for research. A `flux-gen`-for-research capability (generate domain-specific research agents from project context) would close the same quality gap that flux-gen closed for review.

**15. The discourse-fixative mechanism has no observability beyond the reaction round report.**

`discourse-fixative.yaml` triggers corrective injections (for imbalance, convergence, drift, collapse) into reaction prompts before dispatch. The `fixative_context` is built and injected but there is no:
- Tracking of which injections fired across reviews (was drift always triggered? was collapse rare?)
- Analysis of whether fixative injections actually changed reaction quality
- Per-injection effectiveness metric that could inform threshold calibration

The Sawyer flow envelope similarly monitors health but the relationship between health state (healthy/degraded/unhealthy) and actual review quality is unmeasured.

---

### Confidence

| Finding | Confidence | Basis |
|---------|-----------|-------|
| 1. Roadmap emptiness vs system richness | **High** | Directly observable: 2 open items vs extensive system complexity |
| 2. Spec-to-implementation gap | **High** | Spec documents read, reaction/intersynth/AgentDropout not covered |
| 3. Intersynth dependency undocumented | **High** | Synthesize.md delegates to intersynth but no contract document found |
| 4. Discourse subsystem complexity without tests | **High** | Test files listed, none target discourse dynamics specifically |
| 5. Campaign learnings not institutionalized | **High** | One campaign found; learnings not referenced in any guideline |
| 6. flux-review not covered in PRD or spec | **High** | PRD at v0.2.29, plugin at v0.2.56; flux-review not in PRD commands table |
| 7. Domain coverage gaps (AI agents, devops) | **High** | 11 domains listed, known gaps visible in protocol.md draft lines |
| 8. Research synthesis path weaker than review | **High** | Reaction round, peer-findings, and discourse all review-only by inspection |
| 9. Trust model one-way signal flow | **Medium** | Trust multiplier documented; no healing mechanism found but absence of evidence is not certainty |
| 10. Knowledge decay counter not implemented | **Medium** | Spec says "10 reviews"; implementation approximates with "60 days"; approximation acknowledged in AGENTS.md |
| 11. flux-gen agent lifecycle gaps | **Medium** | No lifecycle management code found; could exist outside the plugin |
| 12. Pipeline is procedural not declarative | **High** | SKILL.md structure is sequential prose; configuration options are limited to feature toggles |
| 13. Compact variant drift risk | **Medium** | No equivalence test found; drift risk is structural, not confirmed divergence |
| 14. No domain-specific research agents | **High** | Brainstorm explicitly called this out as v2 work; not yet implemented |
| 15. Fixative observability absent | **Medium** | Fixative fires are reported per-run but not aggregated; could be tracked elsewhere |

---

### Gaps

**What I could not determine from repository inspection alone:**

1. **Intersynth's actual synthesis agent implementation** — I confirmed the delegation call exists in synthesize.md but did not read the intersynth plugin's agent files. The quality of synthesis (and any gaps in how it handles edge cases) is not assessable from interflux alone.

2. **Whether the SKILL-compact.md is behaviorally equivalent to the full SKILL.md** — No equivalence test exists and I did not compare them in detail.

3. **The volume and distribution of production reviews** — The campaigns/flux-review-token-efficiency/results.jsonl suggests some empirical data was collected, but I did not read it. Key questions: which agents are selected most often, what is the Stage 1 completion rate (>50% target per PRD), what is the actual average cost per review type?

4. **The status of bead iv-wz3j ("Role-aware latent memory architecture experiments")** — This is listed as P2/open but I don't know whether work has started outside the bead system or whether the experiment design has been refined.

5. **Whether detect-domains.py has been replaced by LLM-based detection** — The 2026-02-22 brainstorm proposed replacing heuristic detection with Haiku subagent classification. The SKILL.md Step 1.0.1 says "LLM already has the context" and does classification inline without calling detect-domains.py. But detect-domains.py still exists. Whether the replacement was implemented or the script is still used as a fallback was not conclusively determinable.

6. **External ecosystem adoption of flux-drive-spec** — The spec README targets "AI tool developers building multi-agent review systems." I did not determine whether anyone outside Sylveste has adopted or referenced the spec, which would materially affect the priority of closing the spec-to-implementation gap.

<!-- flux-research:complete -->
