# Athenflux Adapter Specification

Status: Draft
Scope: Hermes-native adapter over `interflux`
Canonical upstream: `interflux`
Owning doctrine: `docs/spec/athenverse-adapters.md`
Companion rationale: `docs/research/interverse-athenverse-doctrine.md`

## Purpose

This document defines what `Athenflux` is allowed to add on top of `interflux`, what it must inherit unchanged, and what would qualify it as a real Hermes-native adapter rather than a thin wrapper.

`interflux` remains the canonical review framework, protocol source, and ecosystem-native capability.

`Athenflux` is the Hermes-side operational layer that packages `interflux` for Hermes-native workflows.

## Non-goals

`Athenflux` must not:
- redefine the flux-drive core protocol
- fork `interflux` doctrine without explicit upstream rationale
- become the canonical source of review semantics for non-Hermes clients
- exist solely as a renamed launcher for `interflux`

## Relationship to interflux

### Inherited unchanged from interflux

The following stay canonical in `interflux` and should be treated as inherited behavior unless explicitly overridden with rationale:

- flux-drive protocol semantics
- agent roster meaning and role boundaries
- findings contracts and completion signaling
- severity vocabulary and review verdict framing
- domain detection, staging, and synthesis logic where Hermes has no host-specific reason to diverge
- upstream protocol versioning and reference architecture status

Rule: if a behavior would matter equally in Claude Code, a custom CLI, or another host, it probably belongs in `interflux`, not `Athenflux`.

### Added by Athenflux

`Athenflux` may add Hermes-specific behavior in five broad categories:

1. Orchestration policy
   - when Hermes should trigger review automatically vs explicitly
   - how Hermes chooses between review modes
   - how Hermes decides whether to run local checks before or after review

2. Prompt and synthesis packaging
   - Hermes-native framing around review requests
   - output condensation tuned for Hermes reply channels
   - synthesis style adapted to Hermes memory/tool constraints

3. Artifact lifecycle
   - where review artifacts live in Hermes-oriented workspaces
   - status labels for draft/reviewed/candidate/canonical documents
   - handoff conventions between Hermes sessions and downstream tools

4. Operator workflow semantics
   - default next-step suggestions
   - review-to-plan, review-to-issue, and review-to-execution transitions
   - conventions for when Hermes should save plans, docs, skills, or memory

5. Runtime integration
   - Hermes tool routing and delegation patterns
   - adapter glue to session search, memory, skills, or scheduled workflows
   - host-specific guardrails around token use, process handling, and artifact generation

## Qualification rule

`Athenflux` earns its own name only if it has a behavior contract beyond forwarding.

At minimum, a real `Athenflux` implementation should provide all of:
- a documented Hermes-side workflow that users can intentionally invoke
- at least one stable Hermes-specific synthesis or orchestration convention
- explicit artifact/status semantics for outputs created through the adapter
- a documented boundary showing what remains canonical in `interflux`

If those conditions are not met, the Hermes integration should be described as "Hermes using interflux" rather than as `Athenflux`.

## Proposed behavior contract

### Input contract

`Athenflux` accepts one of:
- a target file or directory to review
- a research/review question with optional paths
- an existing artifact to critique, refine, or canonize
- a request to choose the right interflux review mode for a Hermes task

### Output contract

A compliant `Athenflux` run should produce:
- a concise Hermes-facing summary
- an explicit recommendation or next action
- links or paths to durable artifacts when artifacts are created
- provenance indicating which parts came from canonical `interflux` behavior vs Hermes adapter behavior

### Provenance contract

Every durable `Athenflux` artifact should make clear:
- canonical upstream capability: `interflux`
- adapter layer: `Athenflux`
- whether the artifact is doctrine, plan, implementation note, or synthesis
- current status: Draft, Reviewed, Candidate canonical, or Canonical

## Initial Hermes-specific additions worth standardizing

The following are good candidates for the first real `Athenflux` semantics:

### 1. Review-mode routing for Hermes

`Athenflux` should define a small decision rule for selecting among:
- lightweight targeted review
- full `/flux-drive`
- deep `/flux-review`
- research-first review preparation

This is a host-specific workflow convenience, not a protocol change.

### 2. Hermes-native synthesis shape

`Athenflux` should standardize a concise synthesis layout optimized for Hermes replies:
- what matters most
- what to do next
- whether a durable artifact was created
- whether the result should remain draft or be promoted

### 3. Artifact promotion semantics

`Athenflux` should define a simple promotion ladder for review-derived docs:
- Draft
- Reviewed guidance
- Candidate canonical
- Canonical

This is adjacent to interflux but specifically useful for Hermes-mediated documentation workflows.

### 4. Handoff conventions

`Athenflux` should define when Hermes should:
- save a research note
- update README/AGENTS/CLAUDE references
- create implementation plans
- open or update issues
- save a reusable skill

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

## Open design questions

These questions should be answered before `Athenflux` is promoted beyond Draft:

1. Invocation surface
   - Is `Athenflux` a named Hermes workflow, a plugin, a skill bundle, or a repo?

2. Artifact destination
   - Do `Athenflux` artifacts live first in the source capability repo, a Hermes workspace, or a dedicated Athenverse repo?

3. Review authority
   - When Hermes-specific synthesis disagrees with raw `interflux` findings, what is the authoritative representation?

4. Promotion threshold
   - What minimum implementation depth is required before using the `Athenflux` name operationally instead of doctrinally?

5. Reusability test
   - What would the second adapter need to look like for the Athenverse family to remain crisp rather than ornamental?

## Minimal v0 success criteria

A plausible `Athenflux` v0 would satisfy all of:
- Hermes can invoke `interflux` review modes through a documented adapter workflow
- Hermes emits a stable synthesis format distinct from raw upstream output
- durable artifacts clearly label upstream capability vs adapter layer
- at least one real workflow demonstrates that `Athenflux` adds substantive value beyond command forwarding

## Promotion guidance

### Keep at Draft when
- the adapter is mostly conceptual
- no stable Hermes-specific workflow exists yet
- provenance and ownership boundaries are still fuzzy

### Move to Reviewed when
- at least one Hermes-native workflow has been exercised end-to-end
- output/status conventions are stable enough to document
- upstream vs adapter ownership is explicit and surviving real usage

### Move to Candidate canonical when
- multiple successful Hermes workflows use the same adapter rules
- a second potential Athenverse adapter still fits the doctrine cleanly
- naming and boundary rules survive implementation pressure without drift

## One-line summary

`Athenflux` is the Hermes-native operational layer over canonical `interflux`: it may add host-specific orchestration, synthesis, artifact, and workflow semantics, but it must not replace `interflux` as the source of review protocol truth.
