---
artifact_type: roadmap
project: interflux
version: 0.2.68
last_updated: 2026-05-04
generator: /interpath:roadmap
sources: [bd-jsonl-2026-05-03, plugin.json, docs/plans/2026-04-18-interflux-improvement-plan.md, docs/handoffs/2026-05-02-microrouter-track-b6-start-19-8.md]
---

# interflux Roadmap

**Version:** 0.2.68
**Last updated:** 2026-05-04
**Vision:** [`interflux-vision.md`](interflux-vision.md)
**PRD:** [`PRD.md`](PRD.md)
**Improvement blueprint:** [`../../../docs/plans/2026-04-18-interflux-improvement-plan.md`](../../../docs/plans/2026-04-18-interflux-improvement-plan.md)

## Where We Are

**Plugin state (v0.2.68):** 17 agents (12 review + 5 research), 7 commands, 1 skill (`flux-drive` — unified review/research after the 2026-04-18 B4 consolidation), 2 MCP servers (`exa`, `openrouter-dispatch`), 1 hooks file. ~5,500 LOC of shell + Python in `scripts/`.

### What's Working

- **Multi-model dispatch** — `openrouter-dispatch` MCP routes non-Claude review tiers; `fyo3` epic released 2026-04-12, cross-model cost reduction validated.
- **FluxBench closed-loop scoring** — `s3z6` released; qualification feedback flows to AgMoDB; drift detection live.
- **Hardening bundles shipped** — B1 (flock with timeouts, 6 sites), B2 (AgentSpec TypedDict + `validate_agent_spec()`), B3 (`sanitize_untrusted.py` + persisted openrouter state), B4 (single-source SKILL.md, Phase 2.5 explicit, −255 lines).
- **Category A blueprint fixes** — 17 of 18 immediate fixes shipped through v0.2.61 (silent-failure exits, awk budget bug, severity-trim, JSON-line filter, inotify PID, etc.).
- **Routing contract** — v0.2.68 consumes Clavain B2 routing chain; Codex fixed-tier exception recorded.
- **Roadmap epic burndown** — `sylveste-9lp` now 17 closed / 13 open (P2/P3 polish).

### What's Not Working Yet

- **Microrouter Track B6 (`sylveste-s3z6.19`)** is design-paused — `.19.8` revision hard-blocks `.19.1` design doc, with 4 P0 findings unresolved (safety-floor bypass, circular calibration, audit-trail gap, privacy fall-through).
- **`scripts/` has zero unit tests** despite ~5,500 LOC; only structural/hook tests exist.
- **`v0.2.61` bead `sylveste-n6zw` shows open** while commit `28019e2` reports 17/18 shipped — bead/code drift, needs verification & close-or-reopen.
- **B5, B6, C1, C2, C3, C4 from the blueprint never made it into beads** — six follow-on workstreams are documented but unscheduled.
- **Research-mode parity gap** — peer findings, reaction round, and sycophancy detection live in review mode only.

## Roadmap (Phased)

### Now (P0 / P1 — actively load-bearing)

| ID | Item | Source | Notes |
|----|------|--------|-------|
| `sylveste-s3z6.19.8` | microrouter design revision — calibration independence + holdout protocol | bead | **HARD PREREQ** for `.19.1` design doc; resolve Architecture α/β fork + freeze mechanics |
| `Sylveste-jm4` | Track B6 P0 — `ineligible_agents` placement unspecified, safety floor bypass path | bead (flux-review finding) | feeds `.19.5`/`.19.8` body edits |
| `Sylveste-emv` | Track B6 P0 — circular calibration (judge & baseline same model family) | bead | the "deepest finding" per handoff; Architecture α/β resolution lives here |
| `Sylveste-a5u` | Track B6 P0 — audit-trail unconformity, no-op short-circuit erases resolver state | bead | track for `.19.5`/`.19.6` follow-up |
| `Sylveste-906` | Track B6 P0 — privacy inner-quench, sensitive tasks fall through to cloud | bead | gates `.19.6` privacy-routing extension |
| `sylveste-s3z6.19.1` | microrouter design doc + paper deep-read | bead | blocked by `.19.8` |
| `sylveste-s3z6.19.2` | labeled dataset from interspect verdicts + bead history | bead | blocked by `.19.1` |
| `sylveste-s3z6.19.3` | LoRA distillation pipeline on Qwen3.5-3B-Instruct | bead | blocked by `.19.2` |
| `sylveste-s3z6.19.4` | eval harness — accuracy + downstream pass@1 + latency matrix | bead | blocked by `.19.3` |
| `sylveste-s3z6.19.5` | resolver integration in Clavain `routing.yaml` | bead | blocked by `.19.4`; resolver order verified |
| `sylveste-n6zw` | v0.2.61 — confirm 18/18 Category A immediate fixes shipped, then close | bead | likely just a close-out gap; verify A-08 (`flux-research/` removal) status |
| `sylveste-9lp.16` | research mode parity — peer findings, reaction round, sycophancy detection | bead | promote from P2: closes a real capability gap |

### Next (P2 — planned)

| ID | Item | Source | Notes |
|----|------|--------|-------|
| `sylveste-fyo3.6` | hard budget enforcement mode — test and enable blocking | bead | follow-up to multi-model activation |
| `sylveste-fyo3.7` | Interspect overlay activation — promote from progressive enhancement to default | bead | depends on Interspect health channel readiness |
| `sylveste-9lp.15` | structured disagreement as first-class output (`disagreement_profile`) | bead | unblocks `.16` synthesis quality |
| `sylveste-9lp.17` | passage-level citation in research synthesis | bead | pairs with `.16` parity |
| `sylveste-9lp.18` | evaluation rubrics — finding recall/precision/coverage over time | bead | feeds FluxBench v2 |
| `sylveste-9lp.19` | difficulty-aware slot ceiling — content-signal estimator | bead | replaces static formula |
| `sylveste-9lp.20` | embedding-based dedup pass — cosine on finding titles | bead | quality lift on synthesis |
| `sylveste-9lp.21` | typed agent-state log — JSONL per agent | bead | architectural cleanup |
| `sylveste-9lp.22` | trust model diagnostics — explain low scores, feed back into prompt tuning | bead | activates trust-pipeline value |
| `sylveste-s3z6.19.6` | privacy-routing extension — sensitive tasks always engage router | bead | depends on `.19.5` |
| **NEW** | **C1 — `lib_registry.py` + registry-write consolidation** | blueprint §4 C1 | depends on B1 (✓); 6-8h; unblocks `_fluxbench_score.py` testability |
| **NEW** | **C4 — `flux-review` command → skill refactor (551 → ~20 lines)** | blueprint §4 C4 | depends on B6; 5-7h; mirrors flux-drive structure |
| **NEW** | **B5 — shell hygiene + `MODEL_REGISTRY` canonicalization** | blueprint §3 B5 | independent; 3h |
| **NEW** | **B6 — phase-file instruction accuracy (Composer dead-branch removal, step ordering, Lorenzen path)** | blueprint §3 B6 | prerequisite for C2 + C4; 2-3h |

### Later (P3 / research / aspirational)

| ID | Item | Source | Notes |
|----|------|--------|-------|
| `sylveste-fyo3.10` | weekly discovery agent automation (cron) | bead | requires stable discovery output |
| `sylveste-fyo3.11` | Oracle cross-AI review integration | bead | non-Claude peer review path |
| `sylveste-9lp.25` | learned orchestration from run history | bead | needs labeled negative data first |
| `sylveste-9lp.26` | query decomposition for complex research (v2) | bead | exploratory + onboarding focus |
| `sylveste-9lp.27` | domain-specific research agents (`flux-gen` for research) | bead | pair with parity work |
| `sylveste-9lp.28` | per-finding sycophancy detection | bead | architecture ready in `reaction.yaml` |
| `sylveste-9lp.29` | triage subagent — offload Steps 1.0–1.2 from host context | bead | context-budget play |
| `sylveste-s3z6.19.7` | confidence-cascade verifier (stretch) | bead | post-microrouter |
| **NEW** | **C2 — explicit dispatch state machine + `VerificationStep` primitive** | blueprint §4 C2 | depends on B4 (✓) + B6; 8-12h; most design-intensive |
| **NEW** | **C3 — `sanitize_untrusted.py` fuzz tests + `TrustedContent` NewType** | blueprint §4 C3 | depends on B2 (✓) + B3 (✓); 6-8h |
| **NEW** | **`scripts/` test scaffolding** — `test_validate_agent_spec.py`, `test_sanitize_untrusted.py`, `test_lib_registry.py`, `test_fluxbench_score.py`, shellcheck CI | blueprint §7 | partial coverage today; 0 unit tests in 5.5 KLOC |

## Research Agenda

Open questions surfaced by recent brainstorms and the 2026-04-18 blueprint:

- **Calibration independence** — can microrouter use observed downstream `pass@1` instead of a judge-family anchor (Architecture β)? Requires interspect verdicts to carry actual outcomes, not just judge recommendations. Decision in `s3z6.19.8`.
- **Diversity floor for agent selection** — explore/exploit balance against the reinforcing trust-score loop (blueprint Cat D, deferred to v2 roadmap).
- **AgentDropout threshold** — currently anchored at 0.6, not derived; needs FluxBench data accumulation.
- **Knowledge correctorium separation** — inter-session confirmation tracking lives outside interflux scope; punted to interknow.
- **Discourse-health metric decomposition** — per-severity output schema change blocked by consumer count; FluxBench v2.
- **Athenflux adapter spec** — recently drafted (`docs/spec/athenflux-adapter-spec.md`); validation/integration path still open.

## Companion Status

| Plugin | Role with interflux | Status |
|--------|---------------------|--------|
| clavain | Primary host — interflux is Clavain's review/research engine | shipped |
| interrank | Model recommender — feeds `discover-models.sh` | shipped, integrated 2026-04-08 |
| interspect | Routing evidence channel — feeds microrouter dataset (`s3z6.19.2`) | shipped |
| interknow | Knowledge compounding (relocated from interflux `config/.../knowledge/`) | shipped, migration partial |
| interflect | Dogfood retrospective compounding | scaffold (recent commits `8e027b22`, `d3f47fc9`) |
| openrouter-dispatch (MCP) | Non-Claude model dispatch | shipped, persisted state in v0.2.61 |
| exa (MCP) | Web search progressive enhancement | shipped (graceful fallback if `EXA_API_KEY` missing) |

## Open Beads Summary

```
P0  sylveste-s3z6.19.8         microrouter design revision (HARD PREREQ)
P0  Sylveste-jm4 / -emv / -a5u / -906   four flux-review P0 findings (Track B6)
P1  sylveste-9lp                interflux roadmap epic (13 children open)
P1  sylveste-s3z6 / .19         multi-model + microrouter epics
P1  sylveste-s3z6.19.1..5       microrouter design → integration chain (blocked on .19.8)
P1  sylveste-n6zw               v0.2.61 — verify & close
P1  Sylveste-2lh / -7pq / -96p / -b1e / -d3r / -gxl / -j6t / -t0g / -v3b / -w6j   flux-review P1 findings
P2  sylveste-9lp.15..22         9 quality/architecture polish items
P2  sylveste-fyo3.6 / .7        budget enforcement + Interspect default
P2  sylveste-s3z6.19.6          privacy-routing extension
P3  sylveste-9lp.25..29         5 v2 research items
P3  sylveste-fyo3.10 / .11      weekly discovery + Oracle integration
P3  sylveste-s3z6.19.7          confidence-cascade verifier
```

## Dependency Graph

```
microrouter (Track B6):
  s3z6.19.8 ──► s3z6.19.1 ──► s3z6.19.2 ──► s3z6.19.3 ──► s3z6.19.4 ──► s3z6.19.5 ──► s3z6.19.6
                                                                             └────► s3z6.19.7
  Sylveste-906 ──► s3z6.19.6 (HARD)
  Sylveste-{jm4,emv,a5u,906}  feed body edits to .19.5 / .19.8 (see editor-of-record bead sylveste-lrnk for sequencing)

blueprint workstreams (NOT yet in beads):
  B5  ─── independent
  B6  ──► C2 + C4
  B1✓ ──► C1
  B2✓ + B3✓ ──► C3
  C1, C2, C3, C4  parallel after their B-prereqs

quality/parity series:
  9lp.15 ──► 9lp.16 (research-mode parity) ──► 9lp.17 (passage citation)
  9lp.18 (eval rubrics) feeds FluxBench v2 (post-roadmap)
```

## Keeping Current

- Run `/interpath:roadmap interflux` to regenerate from beads + plans.
- Source of truth is `.beads/issues.jsonl` (export with `bd export -o .beads/issues.jsonl` after Dolt mutations).
- The 2026-04-18 improvement blueprint at `docs/plans/2026-04-18-interflux-improvement-plan.md` carries scope/effort/test-plan detail not duplicated here.

---

## Bead Consistency Audit (this generation)

- **WARNING — Blueprint workstreams without beads:** B5, B6, C1, C2, C3, C4 are referenced by name but not yet tracked. Recommend creating six new beads (one per workstream) under a parent epic or sequenced under `sylveste-qv33` follow-on.
- **WARNING — Open bead with apparent shipped state:** `sylveste-n6zw` open while commit `28019e2` reports 17/18 Category A fixes shipped. Verify A-08 status; if shipped, close `n6zw`; if not, file bead for A-08 alone and close parent.
- **INFO — Microrouter findings re-parented but not closed:** 14 `Sylveste-{jm4,emv,a5u,906,7pq,b1e,2lh,j6t,w6j,96p,gxl,t0g,d3r,v3b}` finding beads from the 2026-05-01 flux-review live as discoverable findings under `s3z6.19`; close as the relevant child completes per handoff guidance.
- **INFO — Dolt/JSONL drift:** Live Dolt DB lacks the 14 microrouter finding beads + `s3z6.19.{1..8}`; only present in `.beads/issues.jsonl` (committed 2026-05-02 `ff59fead`). Run `bash .beads/push.sh` or import on this machine.
