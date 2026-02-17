# Decision Quality Review: Interlens Flux-Drive Lens Agents PRD

**Reviewer:** fd-decisions agent (Flux-drive Decision Quality Reviewer)
**Target:** `/root/projects/Interverse/docs/prds/2026-02-15-interlens-flux-agents.md`
**Date:** 2026-02-16
**Revision:** 2 (post flux-drive review)

---

## Findings Index

| SEVERITY | ID | Section | Title |
|----------|-----|---------|-------|
| P2 | FD-01 | Phased Delivery | Missing Pre-Mortem for Phase 0 Failure |
| P2 | FD-02 | Features (F3) | Premature Optionality Lock-In (MCP Dependency) |
| P3 | FD-03 | Design Decisions | Anchoring Bias in Model Choice |
| P1 | FD-04 | Risks | Blind Spot: No Explore/Exploit Balance Analysis |
| P2 | FD-05 | Phased Delivery | Signpost Vagueness (Success Gate) |
| P3 | FD-06 | Features (F1) | Snake Oil Test: Lens Selection Rationale |
| P2 | FD-07 | Non-goals | Temporal Trade-off Unexamined (Domain Profiles) |
| P3 | FD-08 | Solution | Dissolving the Problem: Why Not Direct MCP Access? |

---

## Detailed Findings

### FD-01 | P2 | Phased Delivery | Missing Pre-Mortem for Phase 0 Failure
**Lens:** N-ply Thinking, Cone of Uncertainty

**What's Missing:**
The Phase 0 success gate ("2/3 test runs produce findings the author says they'd act on") is defined, but the PRD doesn't explore **what happens if Phase 0 fails**. This is a critical strategic decision point:
- Do we pivot to a different review approach?
- Do we revisit the lens selection methodology?
- Do we abandon cognitive review entirely?
- Do we treat "interesting but not actionable" as partial success and iterate?

**Why It Matters:**
Phase 0 is explicitly designed to validate demand risk, but without a pre-planned response to failure, the team is vulnerable to sunk cost reasoning ("we've come this far, let's try Phase 1 anyway") or reactive pivoting. The document calls out actionability risk (#2) but doesn't map decision criteria for **when** to abort vs. refine.

**Recommendation:**
Add a "Phase 0 Decision Tree" section that pre-commits to responses:
- **2/3 success:** Proceed to Phase 1 as planned.
- **1/3 success:** Conduct retrospective with test authors to identify failure mode (lens selection? prompt quality? wrong document types?), then decide: iterate Phase 0 or shelve.
- **0/3 success:** Abort project, document learnings, archive.

---

### FD-02 | P2 | Features (F3) | Premature Optionality Lock-In (MCP Dependency)
**Lens:** The Starter Option, Option Value, Theory of Change

**What's Observed:**
F3 (Interlens MCP Wiring) is blocked until Phase 0 succeeds, which correctly protects against scaling unvalidated work. However, the design assumes MCP integration is **necessary** for scaling ("access to 288 lenses vs. 12 hardcoded"). This commits the project to a specific technical path without testing whether the marginal value of 276 additional lenses justifies the integration complexity.

**Alternative Path Not Explored:**
What if Phase 0 reveals that **12 well-chosen lenses** produce 90% of actionable findings? The MCP integration becomes optional infrastructure, not a Phase 1 blocker. The PRD doesn't test this hypothesis — it assumes "more lenses = better reviews" without evidence.

**Theory of Change Gap:**
The causal chain is:
1. MCP integration → access to 276 more lenses
2. More lenses → better gap detection
3. Better gap detection → more actionable findings

Step 2 is unverified. It's plausible that **diminishing returns** kick in — most cognitive blind spots cluster around 10-20 common frames, and the long tail adds noise, not signal.

**Recommendation:**
Reframe F3 as **conditional** on Phase 1 early data:
- After 5-10 reviews with all 5 agents (using hardcoded lenses), analyze findings: How many findings came from the "top 12" vs. "next 40" vs. "long tail"?
- If 80%+ of findings come from the top 12 per agent, **defer MCP integration** — the value isn't there yet.
- If findings are evenly distributed or the long tail produces critical blind spots, **then** prioritize F3.

This converts MCP from a Phase 1 commitment into a **signpost-triggered decision**.

---

### FD-03 | P3 | Design Decisions | Anchoring Bias in Model Choice
**Lens:** Anchoring Bias, Explore vs. Exploit

**What's Observed:**
Design Decision #1 states: "Sonnet for all lens agents. Cognitive gap detection requires nuanced interpretation — haiku would produce shallow findings."

This is **assertion without testing**. The decision anchors on the assumption that haiku can't do cognitive review, but:
- Haiku is 20x cheaper and 5x faster than sonnet.
- Cognitive review on short documents (<5 pages) may not need sonnet's depth.
- Phase 0 with 3 test runs is the perfect moment to **split-test** haiku vs. sonnet.

**Trade-off Not Explored:**
What if haiku produces 70% of the signal at 5% of the cost? The document frames this as "quality vs. cost" (sonnet wins on quality), but doesn't consider **exploration value** — testing haiku on Phase 0 is nearly free and could unlock a cost-efficient scaling path.

**Recommendation:**
Convert this from a decided constraint to a **Phase 0 experiment**:
- Run 3 test reviews with **both** haiku and sonnet (6 total runs).
- Compare: finding overlap, actionability ratings, review depth, cost.
- If haiku's findings are 70%+ overlapping with sonnet's, make haiku the default and reserve sonnet for complex strategy docs.

This is low-risk exploration during the validation phase.

---

### FD-04 | P1 | Risks | Blind Spot: No Explore/Exploit Balance Analysis
**Lens:** Explore vs. Exploit, Jevons Paradox, Compounding Loops

**Critical Gap:**
The PRD identifies three risks (demand, actionability, cognitive overload) but misses a **fourth, systemic risk**: Creating cognitive review agents may **increase the production of strategy documents** (because now we have a tool to validate them), which increases cognitive review load, which demands more agents, which further legitimizes strategy document proliferation.

This is a **Jevons Paradox** case: Increasing efficiency of strategy validation doesn't reduce strategy overhead — it **amplifies it**. The PRD assumes cognitive review is a net-positive capability, but doesn't ask: **Should we be producing fewer, higher-leverage strategy documents instead of better-reviewed ones?**

**Explore/Exploit Framing:**
The project is in **exploit mode** — it assumes the current rate of PRDs, brainstorms, and plans is correct, and the problem is review quality. An alternative frame: The org is **over-exploring** (too many strategy docs, not enough execution), and cognitive review agents double down on the wrong activity.

**Why This Is P1:**
This isn't a minor oversight — it's a **strategic misalignment risk**. If the real problem is "too much strategizing, not enough building," then this project makes the problem worse, even if it succeeds on its own terms.

**Recommendation:**
Add a fifth risk: **"Meta-Risk: Strategy Inflation."** Before Phase 0, answer:
- What % of Interverse time is spent on strategy vs. implementation?
- Is the bottleneck "bad strategy" or "too much strategy"?
- If cognitive review makes strategy docs 2x better but increases their volume 1.5x, is that a win?

If the answer to #2 is "too much strategy," **shelve this project** and invest in reducing strategy overhead instead.

---

### FD-05 | P2 | Phased Delivery | Signpost Vagueness (Success Gate)
**Lens:** Signposts, Decision Criteria Explicitness

**What's Observed:**
Phase 0 success gate: "At least 2/3 test runs produce findings the author says they'd act on."

This is a **subjective, post-hoc evaluation** with no pre-committed operationalization. What does "would act on" mean?
- "I learned something" (cognitive value, but no behavior change)?
- "I'll keep this in mind next time" (deferred action, hard to verify)?
- "I'm revising this doc now" (immediate action, strong signal)?

**Why Vagueness Is Risky:**
Without clear criteria, the success gate is vulnerable to **confirmation bias** and **motivated reasoning**. If the team is invested in the project, they'll interpret ambiguous feedback as "success." If the test authors are polite, they'll say "interesting!" even if they wouldn't act on it.

**Recommendation:**
Replace the gate with a **three-tier operationalization**:
- **Strong success:** Author revises the doc within 48 hours based on findings.
- **Weak success:** Author says "I'll apply this lens to future docs" (no immediate action, but stated intent).
- **Failure:** Author says "interesting but not actionable" or "I already knew this."

Gate becomes: **At least 2/3 strong success OR 3/3 weak success**. This forces the team to distinguish between "nice to know" and "changed my decision."

---

### FD-06 | P3 | Features (F1) | Snake Oil Test: Lens Selection Rationale
**Lens:** The Snake Oil Test, Survivorship Bias

**What's Observed:**
F1 specifies 12 key lenses for fd-systems, curated from "Systems Dynamics + Emergence + Resilience frames." The acceptance criteria include: "Key lens selection documented in agent file comment: rationale for why these 12 out of 288."

This is **good practice**, but the PRD doesn't define **what makes a rationale valid**. Without a rubric, the rationale could be:
- Post-hoc justification ("I picked these because they felt important").
- Survivorship bias ("These lenses appear often in FLUX examples, so they must be core").
- Circular reasoning ("These lenses define systems thinking, and systems thinking needs these lenses").

**Why This Matters:**
Lens selection is the **highest-leverage decision** in this project. If the 12 lenses are poorly chosen, Phase 0 fails — not because cognitive review is bad, but because we picked the wrong lenses. The PRD doesn't protect against this.

**Recommendation:**
Add a "Lens Curation Rubric" as an acceptance criterion for F1:
- **Coverage:** Do these 12 lenses span feedback, emergence, dynamics, causality, resilience?
- **Orthogonality:** Are the lenses non-overlapping (minimal redundancy)?
- **Historical validation:** Have these lenses appeared in FLUX analyses of past Interverse docs?
- **Concrete applicability:** Can each lens produce a specific, actionable question (not just "consider X")?

Require the rationale to address all four. This converts "document rationale" from a checkbox into a quality gate.

---

### FD-07 | P2 | Non-goals | Temporal Trade-off Unexamined (Domain Profiles)
**Lens:** Temporal Trade-offs, Reversibility, Sour Spots

**What's Observed:**
Non-goal #5: "Domain profile for interlens — lens agents are cross-domain (apply to all document reviews), not project-domain-specific."

This is framed as a **simplification decision** (avoid complexity), but it's actually a **temporal trade-off**: Cross-domain agents are easier to build now but may underperform on specialized domains later. The PRD doesn't ask: **Is this reversible? What's the switching cost if we're wrong?**

**Sour Spot Risk:**
Cross-domain agents give you:
- **Benefit:** Broad applicability (one agent reviews all doc types).
- **Cost:** Generic findings (miss domain-specific traps).

Domain-specific agents give you:
- **Benefit:** Targeted findings (e.g., "go concurrency traps" for codebase docs).
- **Cost:** Maintenance overhead (N domains = N agent sets).

The **sour spot** is: We build cross-domain agents, they produce shallow findings on specialized docs, users ignore them, and we have to rebuild with domain profiles anyway — **wasting Phase 0 and Phase 1 effort**.

**Why This Is P2:**
The PRD treats this as a "not now" decision, but doesn't check: **How much domain context matters for cognitive review?** If systems thinking on a Go concurrency architecture doc requires Go-specific lens applications, the cross-domain approach fails by design.

**Recommendation:**
Phase 0 should **test domain sensitivity**:
- Pick 3 test docs from **different domains** (e.g., Go architecture, marketing strategy, UI design).
- Run fd-systems on all three.
- Evaluate: Do findings feel generic or domain-aware?

If findings are too generic on 2/3 docs, **reject the cross-domain assumption** and revisit domain profiles before Phase 1.

---

### FD-08 | P3 | Solution | Dissolving the Problem: Why Not Direct MCP Access?
**Lens:** Dissolving the Problem, Starter Option, Kobayashi Maru

**What's Observed:**
The solution creates **intermediary lens agents** that call Interlens MCP tools. But the PRD doesn't ask: **Why do we need agents at all? Why not just expose MCP tools directly to flux-drive's synthesis agent?**

**Alternative Framing:**
Current design:
1. User runs flux-drive.
2. Flux-drive invokes fd-systems agent.
3. fd-systems calls `search_lenses` MCP tool.
4. fd-systems writes findings.
5. Synthesis consolidates.

Simpler design:
1. User runs flux-drive.
2. Synthesis agent calls `search_lenses` directly for each document section.
3. Synthesis incorporates lens-based findings inline with technical findings.

This **eliminates 5 agents, F1/F1b/F4, and deduplication complexity**. The trade-off is: Synthesis becomes heavier, and lens findings are less structured. But is that worse than 5 new agents?

**Why This Might Be Better:**
- **Fewer moving parts:** No agent roster explosion, no triage pre-filter complexity.
- **Tighter feedback loop:** Synthesis sees technical and cognitive issues together, can spot interactions.
- **Lower maintenance:** One synthesis prompt update instead of 5 agent files.

**Why This Might Be Worse:**
- **Cognitive overload:** Synthesis already does a lot; adding lens logic may degrade quality.
- **Loss of specialization:** Lens agents can go deeper on specific frames than a general synthesis pass.

**Recommendation:**
Phase 0 should **test both approaches**:
- Run 3 reviews with fd-systems agent (current design).
- Run 3 reviews with synthesis calling `search_lenses` directly (alternative design).
- Compare: finding depth, synthesis coherence, user preference.

If the alternative works, **skip F1b/F3/F4 entirely** and invest in synthesis enhancement instead. This is a classic "dissolving the problem" opportunity — maybe the right answer is "no new agents, better synthesis."

---

## Summary Assessment

### Strengths
1. **Phase 0 as validation gate:** The PRD recognizes demand risk and builds a low-cost test before scaling. This is strong N-ply thinking.
2. **Explicit non-goals:** Avoids scope creep (no API changes, no code review, no auto-generation).
3. **Actionability awareness:** Risk #2 calls out the gap between "interesting" and "actionable" findings.

### Weaknesses
1. **No pre-mortem for Phase 0 failure (FD-01):** The PRD plans for success but not for learning-from-failure.
2. **Explore/exploit blind spot (FD-04):** Doesn't question whether more strategy validation is the right goal.
3. **Premature commitment to MCP (FD-02):** Assumes 288 lenses > 12 lenses without testing diminishing returns.
4. **Vague success gate (FD-05):** "Would act on" is too subjective to reliably gate Phase 1.

### Key Questions for the Author
1. **If Phase 0 fails, what do we do?** (FD-01)
2. **How much do 276 additional lenses matter?** Could we run 10 reviews with 12 lenses/agent and measure coverage before building MCP integration? (FD-02)
3. **Is the bottleneck bad strategy or too much strategy?** If it's the latter, does this project make the problem worse? (FD-04)
4. **What does "would act on" mean operationally?** How do we distinguish politeness from genuine intent? (FD-05)
5. **Have we tested the "no agents, just synthesis + MCP" alternative?** (FD-08)

---

## Verdict

**Needs-changes.**

The PRD has strong phase gating and clear acceptance criteria, but it has **two P1 gaps** (no Phase 0 failure plan, no explore/exploit framing) and **three P2 gaps** (MCP lock-in, signpost vagueness, domain trade-off). Most critically, **FD-04** (strategy inflation risk) questions the project's fundamental premise — this is not a minor refinement issue.

**Recommended actions before Phase 0:**
1. Add a Phase 0 failure decision tree (FD-01).
2. Operationalize the success gate with three tiers (FD-05).
3. Answer the strategy inflation question: Is this project solving the right problem? (FD-04).

**Recommended actions during Phase 0:**
1. Split-test haiku vs. sonnet (FD-03).
2. Test domain sensitivity across doc types (FD-07).
3. Test "synthesis + MCP" alternative vs. "lens agents" (FD-08).

Phase 0 is not just about validating demand — it's about **validating design assumptions**. The PRD treats Phase 0 as "prove the concept," but it should be "prove the concept **and the design choices**."
