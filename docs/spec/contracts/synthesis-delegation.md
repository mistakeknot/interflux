# Synthesis Delegation

> flux-drive-spec 1.0 | Conformance: Core

## Overview

The Synthesis Delegation contract defines the interface between the flux-drive
**host** (the orchestrator that triages, launches, and reports) and the
**synthesizer** (the agent that collects agent outputs, deduplicates findings,
writes verdicts, and produces the human-readable report). The host delegates ALL
synthesis work to the synthesizer so that individual agent prose never enters the
host context — the host reads only the synthesizer's compact return string and
the report file it writes.

In the interflux reference implementation, the synthesizer is the intersynth
plugin (`intersynth:synthesize-review` for review mode,
`intersynth:synthesize-research` for research mode). intersynth is a **separate
plugin with an independent lifecycle**, so this delegation is a cross-plugin
contract, not an internal function call. This document is the single source of
truth for the delegation interface: the input parameters the host passes, the
output artifacts the synthesizer writes, the shape of the return string, the
protocol version that travels with both, and the **mandatory host-side fallback**
that keeps flux-drive functional when the synthesizer is unavailable.

> **Why a contract is needed:** Without it, the host and synthesizer can drift
> silently. If the synthesizer changes its output filename, its return-string
> format, or its expected inputs — or if it is simply not installed — synthesis
> breaks with no detection and no degraded path. This contract makes the
> dependency explicit, versioned, and recoverable.

## Specification

### Protocol Version

Every delegation carries a `synthesis_protocol_version` (current: **`1.0`**).
The host passes it in the delegation prompt as `SYNTHESIS_PROTOCOL_VERSION`, and
the synthesizer echoes it back in the first line of its return string as
`Protocol: {version}`. The version uses semantic versioning, decoupled from both
plugin versions and from flux-drive-spec:

| Change | Bump |
|--------|------|
| Breaking I/O change (renamed/removed param, changed output filename, changed return-string contract) | **major** (e.g. `2.0`) |
| Additive change (new OPTIONAL param, new output field, new SHOULD-level return line) | **minor** (e.g. `1.1`) |

The host knows which major version it expects. If the synthesizer echoes a
**different major version**, the host MUST treat the result as untrusted and fall
back to degraded synthesis (see *Failure & Fallback Behavior*), because the
output schema can no longer be assumed.

> **Why decoupled:** interflux and intersynth ship independently and can be at
> different plugin versions in the same install. The protocol version is the only
> reliable compatibility signal between them — exactly as flux-drive-spec is
> independent of interflux's version (see [README.md](../README.md) § Versioning).

### Input Contract

The host passes named parameters to the synthesizer. This table is canonical;
both the host call sites and the synthesizer agent docs reference it rather than
re-declaring parameters.

#### Common (all modes)

| Parameter | Req | Type | Default | Description |
|-----------|-----|------|---------|-------------|
| `SYNTHESIS_PROTOCOL_VERSION` | REQUIRED | string | — | Protocol version the host speaks (e.g. `1.0`). |
| `OUTPUT_DIR` | REQUIRED | path | — | Directory containing the agent output `.md` files. |
| `VERDICT_LIB` | REQUIRED | path \| `auto` | `auto` | Path to `lib-verdict.sh`, or `auto` to resolve from the synthesizer's plugin root. |

#### Review mode (`intersynth:synthesize-review`)

| Parameter | Req | Type | Default | Description |
|-----------|-----|------|---------|-------------|
| `MODE` | REQUIRED | enum | — | One of `flux-drive`, `quality-gates`, `review`. |
| `CONTEXT` | REQUIRED | string | — | Human-readable review context (input type, stem, agent count). |
| `PROTECTED_PATHS` | OPTIONAL | glob list | `""` | Patterns whose findings are discarded during dedup. Empty = no filtering. |
| `FINDINGS_TIMELINE` | OPTIONAL | path | — | `peer-findings.jsonl` for dedup attribution and the Findings Timeline section. |
| `LORENZEN_CONFIG` | OPTIONAL | JSON | — | Dialogue-game config for move validation. Omitting it disables move validation. |

#### Research mode (`intersynth:synthesize-research`)

| Parameter | Req | Type | Default | Description |
|-----------|-----|------|---------|-------------|
| `RESEARCH_QUESTION` | REQUIRED | string | — | The original research question. |
| `QUERY_TYPE` | REQUIRED | enum | — | `onboarding`, `how-to`, `why-is-it`, `what-changed`, `best-practice`, `debug-context`, or `exploratory`. |
| `ESTIMATED_DEPTH` | REQUIRED | enum | — | `quick`, `standard`, or `deep`. |

> **PROTECTED_PATHS note:** `PROTECTED_PATHS` is documented by the review
> synthesizer (`intersynth/agents/synthesize-review.md`) and MUST be passed by the
> host review call site even when empty, so the documented contract and the wire
> agree. (This contract resolves a prior drift where it was documented but not
> passed.)

### Output Contract

The synthesizer writes files to `OUTPUT_DIR` and returns a compact string. The
host reads the report file and the return string; the host never reads individual
agent `.md` files.

| Mode | Report file | Structured file | Verdict files |
|------|-------------|-----------------|---------------|
| Review | `{OUTPUT_DIR}/summary.md` | `{OUTPUT_DIR}/findings.json` | `.clavain/verdicts/{agent}.json` |
| Research | `{OUTPUT_DIR}/synthesis.md` | — | `.clavain/verdicts/{agent}.json` |

> **Canonical filename:** Review mode writes **`summary.md`** (matching
> [core/synthesis.md](../core/synthesis.md) Step 7 and the host call site).
> Research mode writes **`synthesis.md`**. These names are fixed by this contract;
> a future rename is a major-version bump.

#### findings.json (review mode)

`findings.json` carries the structured findings. Its canonical field set is
defined in [core/synthesis.md](../core/synthesis.md) Step 6 (with the
synthesizer adding discourse-layer annotations: `reactions`, `stemma_analysis`,
`hearsay_analysis`, `dwsq`, `perspectives`, `discourse_health`). Every
`findings.json` MUST include:

```json
{
  "synthesis_protocol_version": "1.0",
  "verdict": "safe|needs-changes|risky"
}
```

> **Schema note (out of scope here):** Three descriptions of `findings.json`
> currently coexist — [core/synthesis.md](../core/synthesis.md) Step 6, the host
> phase file (`skills/flux-engine/phases/synthesize.md` Step 3.4a), and the
> synthesizer agent doc. Reconciling them into one canonical schema is tracked as
> follow-on work; this contract only mandates the `synthesis_protocol_version`
> stamp and points at [core/synthesis.md](../core/synthesis.md) Step 6 as the
> reference definition. (Same problem class as sibling bead `sylveste-rrn4` for
> interweave's QueryResult.)

#### Return string

The synthesizer returns a compact summary (≤15 lines review, ≤10 lines research)
for the host to display immediately. The first line MUST be the protocol echo:

```
Protocol: 1.0
```

The remaining lines are advisory (read by the host LLM / human, not parsed
programmatically) and SHOULD include the verdict and headline counts. The host
displays the return string, then reads the report file for the full report.

### Failure & Fallback Behavior

The synthesizer is REQUIRED for full-fidelity synthesis but MUST NOT be a hard
dependency: flux-drive stays standalone-functional via a degraded host fallback.

#### Detection

The host treats synthesis as failed when any of the following hold:

1. **Synthesizer absent** — the Task tool reports an unknown agent (the
   synthesizer plugin is not installed).
2. **Task error** — the synthesis Task returns an error or times out.
3. **Missing output** — after the Task returns, the expected report file
   (`summary.md` / `synthesis.md`) or `findings.json` (review mode) was not
   written.
4. **Version mismatch** — the returned `Protocol:` major version differs from the
   version the host expects.

#### Degraded host fallback (MANDATORY)

When any detection condition fires, the host performs synthesis itself in a
reduced mode:

1. Read the Findings Index from each valid agent output (≤30 lines/agent, the
   index-first rule from [core/synthesis.md](../core/synthesis.md) Step 2). This
   is the one situation in which the host reads agent files directly.
2. Deduplicate by `section + title` and count convergence (the basic rules from
   [core/synthesis.md](../core/synthesis.md) Step 3).
3. Compute the deterministic verdict (Step 5): any P0 -> `risky`, any P1 ->
   `needs-changes`, else `safe`.
4. Write a minimal `summary.md` (review) / `synthesis.md` (research) and a
   minimal `findings.json` stamped with `synthesis_protocol_version`.
5. **Label the output** — both the report file and the user-facing summary MUST
   begin with the line:

   ```
   degraded synthesis — intersynth unavailable
   ```

   so the degraded path is never silent.

The degraded path **deliberately drops the discourse layer** — reactions,
Lorenzen move validation, stemma analysis, sycophancy scoring, DWSQ, and diverse
perspectives are all synthesizer-only. The core review verdict and the headline
findings are preserved; the cross-agent discourse intelligence is not. This is an
acceptable, explicitly-labeled degradation, not a silent loss.

> **Why mandatory:** Every other progressive enhancement in flux-drive (qmd,
> interrank, interstat, Oracle) has an explicit "skip if unavailable" fallback.
> The synthesizer was the one load-bearing dependency with no fallback and an
> explicit instruction to the host NOT to read agent files. The mandatory
> degraded path closes that gap and makes the "recommended companion" declaration
> in `integration.json` true.

### Dependency Declaration

The synthesizer is declared as a **peer dependency / recommended companion** of
the host, not a hard required dependency:

- It is listed under `peerDependencies` in the host's `plugin.json` and under
  `companions.recommended` in `integration.json`.
- Full-fidelity synthesis (discourse layer + structured findings) REQUIRES it.
- The host MUST implement the degraded fallback above, so flux-drive remains
  standalone-functional without it.

This posture is coherent: "recommended, not required" is true precisely because
the fallback exists.

## interflux Reference

- **Host call sites:** `skills/flux-engine/phases/synthesize.md` Step 3.2
  (research mode lines ~49-67, review mode lines ~69-108). The
  `SYNTHESIS_PROTOCOL_VERSION` and `PROTECTED_PATHS` parameters and the degraded
  fallback are documented there.
- **Echo sites:** `skills/flux-engine/SKILL.md` (Phase 3) and
  `skills/flux-engine/SKILL-compact.md` (Phase 3) name the delegation targets.
- **Synthesizer agents (intersynth):** `agents/synthesize-review.md`,
  `agents/synthesize-research.md`. Their Input Contract sections reference this
  document.
- **Structured output schema:** [core/synthesis.md](../core/synthesis.md) Step 6
  (findings.json) and Step 7 (summary.md).
- **Conformance check:** `tests/structural/test_synthesis_delegation.py` asserts
  the call sites pass the documented inputs and that output filenames agree across
  the contract, the spec, and the host phase file.

## Conformance

An implementation conforming to this specification:

- **MUST** pass `SYNTHESIS_PROTOCOL_VERSION`, `OUTPUT_DIR`, and `VERDICT_LIB` on
  every delegation.
- **MUST** pass `PROTECTED_PATHS` on review-mode delegations (empty string when
  there are no protected paths).
- **MUST** write the report file under the canonical name for the mode
  (`summary.md` for review, `synthesis.md` for research).
- **MUST** stamp `synthesis_protocol_version` into `findings.json`.
- **MUST** echo `Protocol: {version}` as the first line of the return string.
- **MUST** implement the degraded host fallback when the synthesizer is absent,
  errors, produces no output file, or echoes a mismatched major version.
- **MUST** label degraded output with `degraded synthesis — intersynth
  unavailable` in both the report file and the user-facing summary.
- **SHOULD** include the verdict and headline counts in the return string.
- **SHOULD** treat a minor protocol-version mismatch (same major) as compatible.
- **MUST NOT** read individual agent output files in the full-fidelity path —
  delegate all collection to the synthesizer.
- **MUST NOT** fail silently when the synthesizer is unavailable — the degraded
  path is required and must be labeled.
- **MAY** add OPTIONAL input parameters (minor bump) without breaking conformance.
- **MAY** extend `findings.json` with additional fields (minor bump) as long as
  `synthesis_protocol_version` and `verdict` remain present.
