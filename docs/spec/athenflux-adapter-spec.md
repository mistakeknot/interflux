# Athenflux Adapter Specification

Status: Draft
Scope: Hermes-native adapter over `interflux`
Canonical upstream: `interflux`
Upstream compatibility anchor: `interflux` plugin `0.2.68`; `flux-drive` protocol spec `1.0.0`
Owning doctrine: `docs/spec/athenverse-adapters.md`
Companion rationale: `docs/research/interverse-athenverse-doctrine.md`
Review basis: `docs/research/flux-review/athenflux-adapter-spec/2026-05-02-synthesis.md`

## Normative language

This specification uses the following binding vocabulary:

- **MUST** and **MUST NOT** mark requirements for a conforming `Athenflux` artifact or implementation.
- **SHOULD** and **SHOULD NOT** mark strong recommendations; deviations require a recorded rationale.
- **MAY** marks optional adapter behavior.

## Purpose

This document defines what `Athenflux` is allowed to add on top of `interflux`, what it must inherit unchanged, and what would qualify it as a real Hermes-native adapter rather than a thin wrapper.

`interflux` remains the canonical review framework, protocol source, and ecosystem-native capability.

`Athenflux` is the Hermes-side operational layer that packages `interflux` for Hermes-native workflows.

## Non-goals

`Athenflux` MUST NOT:

- redefine the flux-drive core protocol
- fork `interflux` doctrine without explicit upstream maintainer approval
- become the canonical source of review semantics for non-Hermes clients
- exist solely as a renamed launcher for `interflux`
- mediate or capture all Hermes access to `interflux`; direct `interflux` invocation MUST remain available wherever the plugin/runtime supports it

## Relationship to interflux

### Inherited unchanged from interflux

The following stay canonical in `interflux` and are non-negotiable for `Athenflux` unless an `interflux` maintainer approves an upstream compatibility change:

| Inherited behavior | Why it is not localizable |
| --- | --- |
| flux-drive protocol semantics | Protocol semantics must be shared across every host that invokes `interflux`; changing them in Hermes would create a fork. |
| agent roster meaning and role boundaries | Review-agent identity and role boundaries define the upstream review portfolio, not a Hermes display choice. |
| findings contracts and completion signaling | Downstream tools need stable finding and completion semantics regardless of host. |
| severity vocabulary and review verdict framing | Severity must mean the same thing in Claude Code, Hermes, and any future client. |
| upstream protocol versioning and reference architecture status | Version identity is an upstream source-of-truth question, not adapter policy. |

The following may be locally adapted only when the adaptation is explicitly Hermes-specific and records rationale:

| Locally adaptable behavior | Constraint |
| --- | --- |
| domain detection, staging, and synthesis defaults where Hermes has host-specific context | Adapter defaults MUST NOT hide or overwrite upstream `interflux` mode-selection behavior. |
| artifact placement and condensed reply packaging | Condensation MUST preserve finding substance, severity, verdict, and provenance as defined below. |

Boundary test: if a behavior would matter equally in Claude Code, a custom CLI, or another host, it belongs in `interflux` unless a recorded exception explains the Hermes-specific need.

Worked examples:

- **Belongs in `interflux`:** adding a new severity level, changing flux-drive completion criteria, redefining agent roles, or altering the shared finding schema.
- **Belongs in `Athenflux`:** choosing when Hermes asks for a compact Discord-safe synthesis, deciding where Hermes stores a review receipt, or linking review output to a Hermes/Beads pickup handoff.
- **Requires escalation:** a Hermes workflow repeatedly discovers that an `interflux` mode-selection rule is too broad. `Athenflux` may document the local workaround, but the universal rule change must be proposed upstream.

### Added by Athenflux

`Athenflux` MAY add Hermes-specific behavior in five broad categories:

1. Orchestration policy
   - when Hermes should trigger review automatically vs explicitly
   - how Hermes chooses between review modes for Hermes-visible work
   - how Hermes decides whether to run local checks before or after review

2. Prompt and synthesis packaging
   - Hermes-native framing around review requests
   - output condensation tuned for Hermes reply channels
   - synthesis style adapted to Hermes memory/tool constraints

3. Artifact lifecycle
   - where review artifacts live in Hermes-oriented workspaces
   - status labels for draft/reviewed/candidate/local-canon documents
   - handoff conventions between Hermes sessions and downstream tools

4. Operator workflow semantics
   - default next-step suggestions
   - review-to-plan, review-to-issue, and review-to-execution transitions
   - conventions for when Hermes should save plans, docs, skills, or memory

5. Runtime integration
   - Hermes tool routing and delegation patterns
   - adapter glue to session search, memory, skills, or scheduled workflows
   - host-specific guardrails around token use, process handling, and artifact generation

Non-capture constraint: Hermes routing is additive. `Athenflux` may stage or select an `interflux` route for Hermes, but it MUST NOT replace `interflux`'s direct command surface or claim upstream review authority.

## Qualification rule

`Athenflux` earns its own operational name only if it has a behavior contract beyond forwarding.

At minimum, a real `Athenflux` implementation MUST satisfy all of:

- a documented Hermes-side workflow that users can intentionally invoke
- at least one stable Hermes-specific synthesis or orchestration convention
- explicit artifact/status semantics for outputs created through the adapter
- a documented boundary showing what remains canonical in `interflux`
- at least one demonstrated end-to-end Hermes-native workflow with a durable artifact and a review receipt

Verification actor: qualification MUST be verified by an `interflux` maintainer or a designated Athenverse reviewer. The verifier MUST record the qualifying workflow, artifact path, upstream `interflux` version or commit, and any accepted deviations.

If those conditions are not met, the integration MUST be described as "Hermes using interflux" rather than as `Athenflux`.

A partial implementation may be described as "Hermes using interflux with Athenflux draft conventions" when it uses documented Athenflux guidance but has not passed the verification threshold.

## Proposed behavior contract

### Input contract

`Athenflux` accepts one of:

- a target file or directory to review
- a research/review question with optional paths
- an existing artifact to critique, refine, or canonize
- a request to choose the right interflux review mode for a Hermes task

### Output contract

A compliant `Athenflux` run MUST produce:

- a concise Hermes-facing summary
- an explicit recommendation or next action
- links or paths to durable artifacts when artifacts are created
- provenance indicating which parts came from canonical `interflux` behavior vs Hermes adapter behavior
- the upstream `interflux` version or commit used for any conformance claim

### Review-authority precedence

When Hermes-specific synthesis disagrees with raw `interflux` findings, upstream `interflux` findings govern on finding substance, severity, verdict, and protocol meaning.

`Athenflux` synthesis may add Hermes-specific operational guidance, but it MUST NOT overwrite or downgrade upstream finding severity or verdict. Any divergence MUST be represented as a separate Athenflux-side field with rationale.

### Provenance contract

Every durable `Athenflux` artifact MUST make clear:

- canonical upstream capability: `interflux`
- adapter layer: `Athenflux`
- artifact type: doctrine, plan, implementation note, synthesis, receipt, or review staging card
- current status: Draft, Reviewed guidance, Candidate Athenflux-local canon, or Athenflux-local canon
- upstream compatibility anchor: `interflux` version or commit plus relevant protocol/spec version
- finding-level provenance for every imported review finding

Severity survival requirement: severity scores, verdict classifications, blocker status, and finding substance from upstream `interflux` findings MUST survive Hermes condensation unchanged. If Athenflux adds a Hermes-side urgency, priority, disposition, or execution recommendation, it MUST appear in a distinct adapter field rather than replacing the upstream severity/verdict.

Minimal provenance block schema:

```yaml
athenflux_provenance:
  upstream_capability: interflux
  adapter_layer: Athenflux
  artifact_type: synthesis
  status: Reviewed guidance
  interflux_version: 0.2.68
  flux_drive_spec_version: 1.0.0
  source_artifacts:
    - path: docs/research/flux-review/<target>/YYYY-MM-DD-synthesis.md
      method: flux-review
      quality: economy
  findings:
    - id: P1-A
      source: interflux:fd-translation-fidelity
      upstream_severity: P1
      upstream_verdict: blocker
      upstream_blocker_status: blocking-draft-promotion
      upstream_finding_title: "Provenance contract is bibliographic, not semantic"
      upstream_finding_ref: docs/research/flux-review/<target>/YYYY-MM-DD-synthesis.md#p1-a
      upstream_finding_summary: "Condensation can silently rewrite severity or verdict while preserving source labels."
      condensed_summary: "Athenflux artifacts need finding-level provenance and severity survival."
      substance_preserved: true
      substance_preservation_notes: "Condensed summary preserves the original severity, verdict, and finding substance; Hermes-side action is recorded separately."
      athenflux_disposition: accept-for-spec-patch
      athenflux_rationale: "Hermes condensation must not rewrite upstream severity."
```

A durable artifact MAY add richer schema fields, but it MUST preserve the fields above or a documented superset. `substance_preserved: true` is not sufficient by itself; artifacts MUST include a finding title, reference, or summary that lets reviewers audit what substance was preserved.

## Upstream version and skew handling

Athenflux conformance claims MUST name the upstream `interflux` version or commit they were evaluated against.

If upstream `interflux` changes a referenced protocol, finding schema, severity vocabulary, command behavior, or agent roster meaning, Athenflux MUST do one of:

1. update the adapter spec or implementation to match upstream,
2. declare a temporary compatibility window with an expiry/review date, or
3. mark the affected Athenflux behavior non-conformant until review.

Silent skew is not allowed: Hermes summaries and durable artifacts MUST NOT claim current Athenflux conformance when their upstream compatibility anchor is stale or unknown.

## Initial Hermes-specific additions worth standardizing

The following are good candidates for the first real `Athenflux` semantics:

### 1. Review-mode routing for Hermes

`Athenflux` should define a small decision rule for selecting among:

- lightweight targeted review
- full `/flux-drive`
- deep `/flux-review`
- research-first review preparation

This is a host-specific workflow convenience, not a protocol change. The adapter route must remain explainable in terms of direct `interflux` routes.

### 2. Hermes-native synthesis shape

`Athenflux` should standardize a concise synthesis layout optimized for Hermes replies:

- what matters most
- what to do next
- whether a durable artifact was created
- whether the result should remain draft or be promoted

The synthesis shape must preserve upstream finding substance, severity, and verdict as separate fields from Hermes operational recommendations.

### 3. Artifact promotion semantics

`Athenflux` should define a simple promotion ladder for review-derived docs:

- Draft
- Reviewed guidance
- Candidate Athenflux-local canon
- Athenflux-local canon

The local canon labels intentionally avoid unqualified "Canonical" so they cannot be confused with `interflux` as canonical upstream authority.

### 4. Handoff conventions

`Athenflux` should define review-derived handoff conventions for when Hermes should:

- save a research note
- update README/AGENTS/CLAUDE references with review-derived guidance
- create implementation plans from accepted review findings
- open or update issues for review follow-up work
- save a reusable skill only when the review exposes a stable Hermes workflow

## Suggested file and repo boundary

Current recommendation:

- `interflux` repo contains the canonical doctrine for the boundary and the initial adapter spec
- future Hermes/Athenverse repo contains implementation details once `Athenflux` becomes real software rather than doctrine
- both sides should cross-link once implementation begins

## What Athenflux should not own

The following should remain upstream unless proven host-specific:

- generic multi-agent review protocol evolution
- agent scoring semantics intended for all hosts
- canonical review agent identity or portfolio
- generic findings schemas
- framework-agnostic conformance language

## Upstream contribution pathway

When Athenflux dogfood reveals behavior that appears universal rather than Hermes-specific, record it as an upstream contribution candidate instead of silently moving it into Athenflux doctrine.

A contribution candidate SHOULD include:

- the Athenflux workflow or artifact that exposed the need
- why the behavior applies beyond Hermes
- the affected upstream `interflux` protocol/spec/command/agent surface
- proposed owner or reviewer
- disposition: upstream proposal, local exception, or rejected as out of scope

An upstream `interflux` maintainer approves promotion into canonical `interflux` doctrine. Until approved, Athenflux may carry a local workaround only if it is clearly labeled adapter-local.

## Open design questions

These questions should be answered before `Athenflux` is promoted beyond Draft:

1. Invocation surface
   - Is `Athenflux` a named Hermes workflow, a plugin, a skill bundle, or a repo?

2. Artifact destination
   - Do `Athenflux` artifacts live first in the source capability repo, a Hermes workspace, or a dedicated Athenverse repo?

3. Invocation model
   - Is v1 a named Hermes workflow that stages direct `interflux` commands, a parameterized wrapper around `interflux`, or an independent implementation that calls upstream libraries?

4. Reusability test
   - What would the second adapter need to look like for the Athenverse family to remain crisp rather than ornamental?

Review authority and qualification threshold are no longer open questions for Draft: upstream `interflux` findings govern on finding substance/severity, and operational Athenflux qualification requires the verifier-backed demonstration described above.

## Minimal v0 success criteria

A plausible `Athenflux` v0 would satisfy all of:

- Hermes can invoke or stage `interflux` review modes through a documented adapter workflow
- Hermes emits a stable synthesis format distinct from raw upstream output
- durable artifacts clearly label upstream capability vs adapter layer
- at least one real workflow demonstrates that `Athenflux` adds substantive value beyond command forwarding
- a designated verifier records the demonstration artifact and upstream compatibility anchor

## Promotion guidance

### Keep at Draft when

- the adapter is mostly conceptual
- no stable Hermes-specific workflow exists yet
- provenance and ownership boundaries are still fuzzy
- no designated verifier has accepted a qualifying workflow

### Move to Reviewed guidance when

- at least one Hermes-native workflow has been exercised end-to-end
- output/status conventions are stable enough to document
- upstream vs adapter ownership is explicit and surviving real usage
- returned `interflux` findings have been reintegrated without severity/verdict drift

### Move to Candidate Athenflux-local canon when

- multiple successful Hermes workflows use the same adapter rules
- a second potential Athenverse adapter still fits the doctrine cleanly
- naming and boundary rules survive implementation pressure without drift
- upstream compatibility has been rechecked against the current `interflux` version/commit

### Move to Athenflux-local canon when

- the candidate rules survive implementation and review in at least two workflows
- upstream `interflux` maintainers or designated reviewers accept the local-canon label
- any upstream-contribution candidates have explicit dispositions

## One-line summary

`Athenflux` is the Hermes-native operational layer over canonical `interflux`: it may add host-specific orchestration, synthesis, artifact, and workflow semantics, but it must preserve upstream review authority, version anchoring, finding-level provenance, and direct `interflux` availability.
