---
artifact_type: review-synthesis
method: flux-review
target: /home/mk/projects/Sylveste/interverse/interflux/docs/interflux-roadmap.md
target_description: interflux v0.2.68 roadmap — phased work plan with 6 unscheduled blueprint workstreams + active microrouter Track B6 design fork
tracks: 3
track_a_agents: [fd-roadmap-criticalpath, fd-ml-eval-infrastructure, fd-multiagent-orchestration, fd-model-routing-distillation, fd-plugin-release-engineering]
track_b_agents: [fd-broadcast-scheduling, fd-atc-separation, fd-kaizen-testability, fd-handoff-fidelity, fd-decisions]
track_c_agents: [fd-roadmap-criticalpath, fd-ml-eval-infrastructure, fd-multiagent-orchestration, fd-qanat-calibration-drift, fd-scriptorium-queue-irreversibility, fd-noh-shoshin-trust-boundaries, fd-edo-sankin-rotation-scope]
date: 2026-05-04
findings_total: 105
findings_p0: 27
findings_p1: 43
verdict: needs-changes
caveat: Track A subagent embodied agent personas inline rather than dispatching parallel Task subagents; convergence with B/C is genuine cross-session, but Track A's internal agent independence is reduced.
---

# Multi-Track Synthesis — interflux Roadmap

## Verdict

**Needs changes.** 27 P0 + 43 P1 findings across 3 independent tracks. The roadmap is structurally sound but has 8 high-confidence convergent gaps and ~15 missing strategic commitments. The dominant cross-cutting pattern: **the roadmap names calibration loops without specifying the holdouts that ground them**, and **records six load-bearing workstreams (B5/B6/C1–C4) without bead primitives** so automation cannot schedule any of them.

## Cross-Track Convergence (Highest Confidence)

Findings ranked by independent-track convergence score.

### CONV-1 [3/3 tracks] — Six blueprint workstreams unbeaded

A (theme 4), B (P1-1), C (P0-A). All three independently flagged that B5/B6/C1/C2/C3/C4 carry effort estimates and dependency edges (`B6 → C2+C4`, `B1✓ → C1`, `B2✓+B3✓ → C3`) but have no bead IDs. C1 and C3 have all B-prereqs already shipped — only the missing bead keeps them out of rotation. The audit footnote names the gap but does not fix it. **Severity: P0** (`bd list --priority 1` returns the wrong work surface; recurrence pattern across regenerations).

**Action:** Create 6 beads under parent `sylveste-qv33`. Order: B6 first (gates C2+C4); B5 in parallel; C1, C3 ready immediately; C2 + C4 after B6 closes.

### CONV-2 [3/3] — Architecture α/β fork is option-destroying with no decision authority

A (theme 1), B (P0-1), C (P0-D + P0-F). The `.19.1`–`.19.6` chain is downstream of an irreversible epistemic commitment — once `.19.3` (LoRA training) runs under the chosen architecture, switching costs weeks. Roadmap row carries no decision deadline, no named decision authority, no re-entry cost. β depends on an unbeaded interspect schema extension (`task_outcome` column) that is itself a multi-week project. C surfaced **Architecture γ** (judge-ensemble across disjoint model families) which the α/β framing erases. **Severity: P0**.

**Action:** Add to `.19.8` row: explicit α/β/γ evaluation table + decision deadline + decision-authority owner. File new bead `s3z6.19.0` for interspect outcome-column extension, OR commit explicitly to α and de-risk with γ.

### CONV-3 [3/3] — 3-month Sylveste deferral is invisible to prioritization

A (theme 5), B (P0-2), C (strategic gap). The binding schedule constraint never enters the prioritization function. P0/P1/P2/P3 ordering is constraint-neutral, ignoring the slack window. Pre-launch readiness work (test scaffolding, kill-switch tests, telemetry, contract pinning, link checks, spec policy, rollback tests, privacy threat model) is in P3 while behavioral polish is P2 — exactly inverted against a de-risking window. **Severity: P0** (strategic).

**Action:** Add a "Pre-Launch Readiness" section to the roadmap (separate from priority phases) with 6-8 named beads. Re-shift items: test scaffolding → Now P1; behavioral polish that doesn't ship to users → Later.

### CONV-4 [3/3] — Multi-destination coupling of P0 finding beads with no merge protocol

A (theme 2), B (P0-4), C (P0-C, P0-H). `Sylveste-jm4` "feeds body edits to `.19.5`/`.19.8`" — two destinations, ambiguous order. `Sylveste-a5u` similar. `Sylveste-emv` has no destination ID. `Sylveste-906`'s "gates `.19.6`" is in Notes but absent from the dependency graph. Two sessions could produce conflicting edits to the same design-doc section. **Severity: P0**.

**Action:** Replace "feed body edits to" with explicit CPM verbs (`hard-blocks`, `informs non-blocking`). State whether `.19.8`'s close-criterion includes all 4 P0 findings closed. Add `Sylveste-906 ──► .19.6 (HARD)` to the dependency graph block.

### CONV-5 [3/3] — `9lp.16` promoted over its declared blocker `9lp.15`

A (reprioritization), B (P1-6 indirect via parity description gap), C (P1-1). `9lp.15` is explicitly noted as "unblocks `.16` synthesis quality" — but `.15` is in Next P2 while `.16` is in Now P1. Shipping `.16` without `.15` delivers peer findings + reaction round whose structured disagreements have nowhere to land. **Severity: P1**.

**Action:** Co-promote `9lp.15` to Now P1, OR gate `9lp.16` rollout. Add ordering annotation to `.16`: sycophancy detection runs as a synthesis-gate, not a post-synthesis report.

### CONV-6 [2/3 — A+B] — Dolt/JSONL drift is named but not gated

A, B (P0-3). The roadmap audit footnote flags 22 microrouter beads in JSONL but missing from local Dolt. Cited `bd list --priority 0` returns zero against live Dolt — automation reading Dolt cannot see the four safety-floor beads. **Severity: P0**.

**Action:** Add the drift fix as a **prerequisite gate** in the Now section, not an audit footnote. One bead: "Reconcile `.beads/issues.jsonl` ↔ Dolt; add CI check that fails when JSONL has IDs Dolt does not."

### CONV-7 [2/3 — A+C] — Circular calibration anti-pattern recurs unnamed at multiple layers

A (theme 1), C (P0-D, P0-E). The pattern flagged in `Sylveste-emv` for microrouter recurs identically in: (a) the trust-score loop (9lp.22 fixes it but is P2 Next), (b) AgentDropout 0.6 threshold (anchored not derived, no calibration bead), (c) FluxBench scoring (no external ground truth), (d) `9lp.16` sycophancy detection (judge proximal to detector). **Severity: P0** structural.

**Action:** Add a "Holdout Register" — one table naming the ground-truth source for each calibration loop in the system. Promote `9lp.22` to Now P1; add bead for AgentDropout calibration; add diversity-probe exit criterion to `9lp.22` (currently filed under v2-deferred per blueprint Cat D, should be Now P1).

### CONV-8 [2/3 — B+C] — `n6zw` drift recurrence has no acceptance predicate

B (P1-3), C (P0-A overlap). CLAUDE.md says A-08 is `git rm`; AGENTS.md says rename to `flux-research-legacy/`. The roadmap audit warning flags this but doesn't define the close predicate. Recurrence is structural: every regeneration will re-flag. **Severity: P1**.

**Action:** Define close predicate inline ("`flux-research/` directory absent OR explicitly renamed; CLAUDE.md + AGENTS.md agree"). Verify, then close `n6zw` or file follow-up bead for residual A-08.

## Track A — Domain-Expert Insights

**Adjacent specialists added 8 single-track findings the other tracks missed:**

- A1 (`fd-roadmap-criticalpath`) — **Broken doc link at roadmap line 16** (`../../docs/plans/...` should be `../../../docs/plans/...`). Trivial fix.
- A2 (`fd-ml-eval-infrastructure`) — **`.19.2` dataset inherits class imbalance from interspect verdict distribution** (~92% no-override). β fix can't compensate for label scarcity.
- A3 (`fd-model-routing-distillation`) — **Privacy + audit-trail compound to silent exfiltration path** (Sylveste-906 + Sylveste-a5u together). Currently filed as separate beads with no link.
- A4 (`fd-multiagent-orchestration`) — **AgentDropout silent zero-agent failure** if all candidates fall below 0.6. No safe-default behavior specified.
- A5 (`fd-plugin-release-engineering`) — **`Codex fixed-tier exception` durability** (recorded 2026-04-26): commit message records the exception but no bead tracks the decision-revisit trigger.

## Track B — Operational-Pattern Insights

**Parallel-discipline agents added 3 single-track findings:**

- B1 (`fd-handoff-fidelity`) — **`docs/handoffs/latest.md` symlink is stale (points to 2026-04-10)** while interflux has commits and beads through 2026-05-02. Cold-start sessions land on wrong context.
- B2 (`fd-atc-separation`) — **No editor-of-record protocol for shared design-doc sections** under concurrent P0 edits. Standard ATC pattern: explicit hand-off slot.
- B3 (`fd-kaizen-testability`) — **C2/C4 add behavior; test scaffolding stays P3** — defect-cluster root cause is order-of-operations.

## Track C — Structural Insights from Distant Domains

**Esoteric agents converged on two root causes (qanat + scriptorium lenses both):**

- C1 (qanat lens) — **Calibration loops without external ground truth.** All four interflux loops (microrouter, FluxBench, AgentDropout, trust-score) have *internal* feedback — the qanat mirab pattern (water allocation arbitrated by a party outside the irrigation system) names what's missing: a holdout that sits *outside* any of the loops.
- C2 (scriptorium lens) — **Irreversible operations without pre-commit verification contracts.** C2/C4/`.19.3` LoRA training are scriptorium "gold-leaf moments" — single-pass, expensive to reverse. Roadmap rows lack the rota: who verifies, against which standard, before commit.
- C3 (Noh shoshin lens) — **C3 TrustedContent NewType has no consumer-site propagation plan.** Type-safety without consumer adoption is theatre.
- C4 (Edo sankin-kotai lens) — **10 P1 flux-review findings have no Now/Next/Later destination** — corridor monopoly: they sit in Open Beads Summary but no row pulls them in.

## Strategic Items the Project Should Commit To But Hasn't

Cross-track convergent. None currently named in the roadmap.

1. **Holdout Register** — One table naming the ground-truth source for each calibration loop (fixes CONV-7).
2. **Pre-Launch Readiness section** — separate from priority phases, time-boxed to deferral window (fixes CONV-3).
3. **Brainstorm-to-roadmap lift discipline** — `.19.8` brainstorm contains commitments (snapshot SHA, holdout protocol) that the roadmap row drops; add a step to `/interpath:roadmap` (or a checklist) to lift brainstorm commitments into rows.
4. **Spec/code drift policy for `flux-drive-spec 1.0.0`** — currently no rule for when spec must match implementation.
5. **interknow migration completion criterion** — local `config/flux-drive/knowledge/` directory persists with one file unique to it; close the migration or revert.
6. **Athenflux adapter validation owner + schedule** — drafted spec, no bead, no scheduling.
7. **interflect dogfooding schema** — recent commits scaffold it but no `interverse/interflect/` directory exists yet; clarify status or close.
8. **Bead-creation deadline policy** — recurrence-pattern fix: blueprint workstreams must have beads within N days of plan-doc landing.
9. **interflux↔Clavain phase-tracking boundary** — currently caller-responsibility per CLAUDE.md but no tested integration contract.
10. **Non-Claude → interknow trust contract** — multi-model dispatch + knowledge compounding intersect with no policy.

## Reprioritization Recommendations

| Bead | Currently | Move to | Reason |
|------|-----------|---------|--------|
| `sylveste-9lp.15` | Next P2 | **Now P1** | Declared blocker of `.16`; CONV-5 |
| `sylveste-9lp.22` | Next P2 | **Now P1** | Trust diagnostics fixes circular-calibration recurrence; CONV-7 |
| `9lp.18` (eval rubrics) | Next P2 | **Now P1** | Pre-launch readiness gate; rates the system before launch |
| Diversity probe | v2-deferred | **Now P1** (as exit-criterion of `9lp.22`) | Loop-deepener ships before loop-offset; CONV-7 |
| C2 dispatch state machine | Later P3 | **Next P2** | Closes `Sylveste-a5u`; gates audit-trail integrity |
| C3 sanitize fuzz tests | Later P3 | **Next P2** | Live security boundary, no test coverage |
| Test scaffolding (whole) | Later P3 | **Now P1** | Pre-launch readiness; CONV-3 |
| `Sylveste-906` absorption | "follow-up to .19.5/.19.6" | Hard-block on `.19.5` | Privacy + audit-trail compound; A3 |
| `Sylveste-a5u` absorption | "follow-up to .19.5/.19.6" | Hard-block on `.19.5`; closure-criterion of C2 | CONV-4 + CONV-2 |

## Summary Assessment

The roadmap is **factually current and well-structured** — the regeneration captured the multi-model release, microrouter design fork, and blueprint workstreams accurately. What it lacks is **operational discipline**: every load-bearing commitment that lives in plan docs or brainstorms must be lifted into beads + rows; every calibration loop must name its holdout; every irreversible operation must name its pre-commit verifier.

The single highest-leverage change: **create the six blueprint beads + `s3z6.19.0` interspect-extension bead today**, before this roadmap regenerates again. That alone closes CONV-1 + CONV-2 + CONV-7's actionable component, fixes the recurrence pattern, and makes `bd list` return the actual work surface.

The semantic-distance value was real: Track C's qanat + scriptorium lenses surfaced the **holdout-register-missing** and **pre-commit-verification-missing** patterns that no inner-track agent named, even though every inner-track agent's findings were instances of those patterns.

## Caveats

- **Track A independence reduced:** the orchestrator embodied each agent's persona inline (Task tool unavailable in its context) rather than dispatching parallel subagents. Findings remain useful; convergence claims with B and C are genuine (different sessions, different model — opus vs sonnet for B/C) but Track A's internal cross-agent independence is weaker than B and C.
- **Track C raw findings underwent 51 → 28 dedup pass internally;** lower numerical findings count vs. Track A doesn't reflect lower depth.
- **Track B agent count was 4 declared, 5 reported** — `fd-decisions` is a synthesis agent, not a generated reviewer.
