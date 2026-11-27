# Phase Review (Advisory Cognitive Review at Workflow Transitions)

> flux-drive-spec 1.0 | Conformance: Extension | **Status: Draft proposal (2026-11-26) — not implemented**

## Overview

Run flux-drive's cognitive reviewers on a planning document automatically when a workflow moves from one phase to the next: brainstorm → PRD, PRD → plan, and optionally plan → execute. The review is **advisory**. It surfaces blind spots in the document at the moment they are cheapest to fix, but it never blocks a phase transition.

The capability already exists and has been validated. The five cognitive agents (`fd-systems`, `fd-decisions`, `fd-people`, `fd-resilience`, `fd-perception`) are document-only reviewers. Today they run only when someone remembers to invoke `/flux-drive` on a document. This extension defines the contract that lets a workflow host invoke them at the right moment without a person having to remember.

## Goals

1. Review each planning document once per phase transition, at low enough cost and noise that the review stays on by default.
2. Keep phase ownership with Interphase. Per `CLAUDE.md`, phase tracking is the caller's responsibility and interflux does not source `lib-gates.sh`. interflux only exposes a review profile; Interphase decides when to call it.
3. Avoid re-flagging issues the previous phase already raised and resolved.
4. Produce a short, machine-readable result the host can show in one or two lines.

## Non-goals

- **A blocking gate.** Cognitive findings are judgment calls about strategy, not correctness defects. This extension never fails a transition. Shipping gates stay with intercore's sprint-gate enforcement, which is unchanged.
- **Running `/flux-review`.** It regenerates agents on every run, which `guide-choosing-flux-command.md` calls wasteful for automated pipelines. Phase review uses `flux-drive` with existing agents.
- **Reviewing code or diffs.** Cognitive agents never run on code. Technical review at implementation time stays with the existing quality-gates flow.
- **Moving phase logic into interflux.** interflux gains invocation options; it learns nothing about phase state.

## Division of responsibility

| Concern | Owner |
|---|---|
| Detecting a phase transition and deciding whether to review | Interphase |
| Choosing the document and locating the prior phase's review | Interphase, using its own state |
| Triage, dispatch, synthesis | interflux (`flux-drive`) |
| Deduplicating against prior-phase findings | interflux, given the prior `findings.json` by the caller |
| Showing results and optionally linking them to beads | Interphase (uses the existing `beads` integration in `integration.json` when a bead exists) |
| Persisting the opt-in/opt-out setting | Interphase config |

## Trigger points

| Transition | Document reviewed | Default | Rationale |
|---|---|---|---|
| brainstorm → PRD | the brainstorm | **opt-in** | Brainstorms are exploratory and cheap; reviewing every one risks the strategy-inflation loop (see Risks). |
| PRD → plan | the PRD | **on** | The highest-leverage point: scope, success criteria and decision quality get locked in here. |
| plan → execute | the plan | **on** | Last cheap point to catch sequencing, resilience and dependency gaps before code exists. |

The caller passes the transition as `--phase` using the values below. Today `--phase` feeds only B2/B3 model routing, and it keeps that role.

| `--phase` value | Meaning |
|---|---|
| `brainstorm-review` | reviewing a brainstorm before PRD |
| `prd-review` | reviewing a PRD before planning |
| `plan-review` | reviewing a plan before execution |

## Invocation contract

```
/interflux:flux-drive <document> \
  --phase=<brainstorm|prd|plan>-review \
  --profile=phase-review \
  [--quality-gates-plan-coverage=<covered|not-covered|unknown>] \
  [--prior-findings=<path to previous phase's findings.json>] \
  [--prior-source-path=<canonical path> --prior-source-sha256=<64 lowercase hex digits>] \
  [--output-dir=<caller-chosen stable dir>]
```

### New option: `--profile=phase-review`

Applies a named bundle of settings so callers don't have to replicate them:

| Setting | Value | Why |
|---|---|---|
| Roster | Cognitive agents, plus `fd-user-product` for `prd-review`. For `plan-review`, include `fd-architecture` only when Interphase passes `--quality-gates-plan-coverage=not-covered`; otherwise omit it and record the reason. No technical agent runs for `brainstorm-review`. | A plan may need technical design review, but duplicate architecture coverage adds noise and cost. |
| Slot ceiling | 4 (brainstorm), 5 (prd, plan) | Keeps cost and output size bounded. The normal dynamic ceiling is 4–10. |
| Stage 2 expansion | Disabled | Advisory reviews don't escalate. |
| Reaction round | Disabled | Halves synthesis cost. Reactions add little to cognitive findings. |
| Budget | The existing per-type budgets in `config/flux-drive/budget.yaml` (`brainstorm: 80000`, `prd: 120000`, `plan: 150000`) | No new budget keys. |
| Interactivity | Non-interactive (already the default) | Must never prompt inside a pipeline. |
| Verdict | Recorded but labeled advisory (see Output) | The caller must not gate on it. |

Triage scoring is unchanged. Within the restricted roster, agents are still scored and pre-filtered as `core/scoring.md` describes. Document-type detection already gives cognitive agents base score 2 for PRD/brainstorm/plan (`skills/flux-engine/SKILL.md`, cognitive pre-filter).

For `plan-review`, Interphase passes `--quality-gates-plan-coverage=not-covered` only after establishing that quality-gates will not review this plan. `covered` means it will; `unknown` means Interphase cannot establish either state. Omitted or malformed values are treated as `unknown`. interflux omits `fd-architecture` for `covered` and `unknown` and records the value and omission reason in `phase_review.architecture`. Other phases ignore this option and never add `fd-architecture` through it.

### New option: `--prior-findings=<path>`

Interphase stores the previous phase's `findings.json` path in its own state alongside the source document's canonical path and SHA-256, and passes all three values to interflux, for example the brainstorm review when reviewing the PRD. A bead field is not required. The prior findings carry that source path and hash as lineage. Interphase passes the pointer only when its stored lineage matches the intended preceding document; interflux compares the two `--prior-source-*` values with the prior findings' lineage before classifying. If any of the three options is missing, the lineage is missing, or the values disagree, treat the pointer as absent and report a diagnostic. Synthesis classifies each new finding against a validated prior file:

| Class | Rule | Shown to the user? |
|---|---|---|
| `new` | No match in the prior findings | Yes |
| `repeated` | Matches a prior finding: same agent family, and a section/title similarity at or above the existing dedup threshold | Show if severity rose or current severity is P0, even when unchanged. A rise is the `escalated` subcase of repeated; it contributes to `repeated` and `repeated_escalated` counts. Mark an unchanged P0 as repeated. Other unchanged findings are counted, not listed. |
| `resolved` | A prior finding with no match now | Listed as a one-line "addressed since <phase>" note |

Matching reuses the synthesis dedup machinery (`core/synthesis.md` Step 3). No new matcher is introduced. If `--prior-findings` is absent, unreadable or has mismatched or missing lineage, every finding is `new`, and the run still succeeds.

### Skip conditions (caller-side signal gate)

The caller should **not** invoke phase review when any of these hold, and should record the skip reason:

1. The document is under a minimum size (proposed default: 40 non-blank lines). Thin documents produce generic findings.
2. The document's content hash matches the last reviewed version for this phase. Nothing changed.
3. The user or project has opted out (`phase_review.enabled: false`, or that transition disabled).
4. The pre-dispatch estimate from `scripts/estimate-costs.sh` exceeds the type budget and `enforcement: hard` is set.

## Output contract

The run produces the normal `findings.json` and `summary.md`. This extension adds a `phase_review` block to `findings.json`:

```json
"phase_review": {
  "phase": "prd-review",
  "advisory": true,
  "profile": "phase-review",
  "prior_findings": "docs/research/flux-drive/<brainstorm-stem>-<hash>/findings.json",
  "prior_findings_status": "matched",
  "source_document": {"path": "docs/design/example-prd.md", "sha256": "<64 lowercase hex digits>"},
  "architecture": {"included": false, "quality_gates_plan_coverage": "not_applicable", "reason": "phase is prd-review"},
  "counts": {"new": 4, "repeated": 2, "repeated_escalated": 0, "resolved": 3},
  "headline": [
    {"id": "P0-1", "agent": "fd-resilience", "severity": "P0", "class": "repeated", "title": "Unresolved critical risk"},
    {"id": "P1-1", "agent": "fd-decisions", "severity": "P1", "class": "new", "title": "Success gate is not operationalized"}
  ]
}
```

- `advisory` is always `true` under this profile. A caller **must not** turn `verdict` into a blocking outcome when `phase_review.advisory` is true.
- For a `plan-review`, `architecture` records `included`, the caller's `quality_gates_plan_coverage` value, and a reason when omitted. For other phases the value is `not_applicable`. `prior_findings_status` is `matched`, `absent`, `unreadable` or `lineage_mismatch`; only `matched` permits comparison.
- Each `headline` entry carries `severity` and `class` (`new`, `repeated` or `escalated`). An escalated finding also counts as repeated. `headline` holds **every P0**, whether new, unchanged repeated or escalated to P0, followed by at most 3 highest-severity non-P0 `new` or escalated findings. P0 visibility is deliberately uncapped. Interphase shows every P0 inline; if the display needs more than two lines, it expands rather than hiding a P0.
- Once PR #53 (issue #52) merges, its cross-model confidence labels apply here too, so an all-Claude roster can't present correlated agreement as "High".

**Caller display (recommended):** `Phase review (PRD): 4 new · 3 resolved since brainstorm · P0: [repeated] Unresolved critical risk · top non-P0: [P1] Success gate is not operationalized — summary: <path>`. Show every P0 from `headline`, including repeated ones, before the capped non-P0 summary. Details stay in `summary.md`. The caller may link `headline` findings to the work item via the `beads` integration.

## Risks and mitigations

| Risk | Source | Mitigation |
|---|---|---|
| **Strategy inflation**: easier validation of strategy docs increases their volume (a Jevons effect) | fd-decisions FD-04 on the cognitive-agents PRD | Advisory only. Brainstorm review is opt-in. Track document volume per sprint before and after rollout (see Validation). |
| Noise and alert fatigue | — | Restricted roster and agent slot ceiling, three-item cap on non-P0 headlines, suppression of unchanged repeated findings below P0, size gate |
| Cost creep across many transitions | — | Existing per-type budgets, no Stage 2, no reaction round, content-hash skip |
| Correlated agreement presented as confidence | review finding C-4 | Weighted cross-model convergence from #52 (PR #53, pending merge) |
| Re-flagging resolved issues every phase | — | `--prior-findings` classification |
| Pressure to turn advisory into a gate | — | `advisory: true` contract, plus an explicit non-goal in this spec |

## Validation (Phase 0, before default-on)

The cognitive-agents PRD review (FD-01, FD-05) asked for pre-committed, operational success criteria. Here they are:

- **Trial:** enable `prd-review` and `plan-review` on 10 real transitions.
- **Actionability:** the share of runs where the author edits the reviewed document within 48 hours in response to a `headline` finding.
  - **≥ 50%:** make it default-on.
  - **20–50%:** keep it opt-in, review which agents produced the acted-on findings, and narrow the roster.
  - **< 20%:** shelve the extension and record why.
- **Cost:** median spend per run at or under 60% of the type budget.
- **Volume check:** planning documents per sprint should not rise more than 25% against the pre-trial baseline. A larger rise means the strategy-inflation risk is real, and brainstorm review stays off.

## Required changes

### interflux (this repo)
1. `skills/flux-engine/SKILL.md`: parse `--profile=phase-review` and `--prior-findings`, and document the `--phase` values above.
2. Triage: apply the profile's roster restriction and slot ceiling, and disable Stage 2 and the reaction round under the profile.
3. Synthesis: validate the prior-source lineage and classify findings against matching `--prior-findings`, then emit the `phase_review` block and `headline`.
4. `docs/spec/core/synthesis.md`: document the `phase_review` block. Add a `docs/spec/README.md` row for this extension.
5. Tests: profile and coverage-option parsing; roster restriction per phase, including `fd-architecture` inclusion only for `not-covered` and recorded omission reasons for `covered`/`unknown`; prior-findings lineage match and mismatch; classification (`new`/`repeated`/`escalated`/`resolved`); all new, repeated and escalated P0s in the headline and caller display without a cap; `class`/`severity` markers; the three-item non-P0 cap; and `advisory: true` with a repeated P0.

### Caller (Interphase — tracked in that repo)
1. Hook the brainstorm→PRD, PRD→plan and plan→execute transitions.
2. Apply the skip conditions, then invoke `flux-drive` with the contract above.
3. Store each phase's `findings.json` path with its source document path and SHA-256 in Interphase's own state so the next transition can pass a matching pointer as `--prior-findings`; do not require a bead field. Determine the quality-gates plan-coverage value for `plan-review`, defaulting to `unknown`.
4. Show the one-line result, and optionally link `headline` findings to beads.
5. Add config: `phase_review.enabled`, per-transition toggles, and the size threshold.

## Draft design choices

1. Interphase owns the phase-transition hook. Intercore's sprint gates remain separate.
2. A plan review includes `fd-architecture` only when quality-gates will not cover the same plan. If Interphase cannot establish that condition, it omits the agent and records why.
3. Interphase owns the prior-review pointer in its own state and passes an explicit path; interflux does not require a bead field.
4. An unchanged repeated P0 remains visible in the brief result and full report, marked `repeated`. The review stays advisory and never blocks a transition.
