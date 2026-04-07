# Findings Index Format

> flux-drive-spec 1.0 | Conformance: Core

## Overview

The Findings Index is the structured output contract between agents and the orchestrator. Every agent produces a Findings Index as the first block of its output — a machine-parseable summary of everything it found. The orchestrator reads indices first, only falling back to prose when it needs additional context. This separation is what makes synthesis fast and deterministic: the orchestrator never has to interpret free-form prose to understand what agents found.

## Specification

### File Structure

Each agent writes its output to `{OUTPUT_DIR}/{agent-name}.md`. The file has two sections:

1. **Findings Index** (first block, machine-parsed)
2. **Prose sections** (after the index, human-readable)

The orchestrator parses only the Findings Index for synthesis. Prose sections provide evidence and rationale for human readers.

### Index Format

The Findings Index starts with a heading and contains zero or more finding lines followed by a Verdict line:

```
### Findings Index
- P1 | AR-001 | "Authentication" | Session tokens stored in localStorage
- P2 | AR-002 | "API Design" | Missing rate limiting on public endpoints
- P3 | AR-003 | "Naming" | Inconsistent use of "user" vs "account" in models
Verdict: needs-changes
```

Each finding line follows this exact format:

```
- SEVERITY | ID | "Section Name" | Title
```

| Field | Format | Description |
|-------|--------|-------------|
| SEVERITY | `P0\|P1\|P2\|P3` | Severity level (see below) |
| ID | `[A-Z]{2,3}-\d{3}` | Agent-scoped unique identifier (prefix from agent, sequential number) |
| Section Name | Quoted string | The section or area of the document/code this finding applies to |
| Title | Free text | One-line description of the finding |

> **Why this works:** The pipe-delimited format is trivially parseable (split on ` | `) while remaining human-readable. The quoted section name handles spaces and special characters. The ID prefix provides agent attribution without additional metadata.

### Severity Levels

| Level | Meaning | Impact on Verdict |
|-------|---------|-------------------|
| P0 | Critical — blocks shipping, security vulnerability, data loss risk | Any P0 → verdict `risky` |
| P1 | Important — significant issue that should be fixed before merge | Any P1 → verdict `needs-changes` |
| P2 | Moderate — quality issue worth addressing, won't block | Does not affect verdict |
| P3 | Minor — suggestion, nitpick, or improvement idea | Does not affect verdict |

> **Why this works:** Four levels hit the sweet spot — enough granularity to distinguish "fix this now" from "consider this later," but not so many that agents agonize over P4 vs P5. The verdict mapping is deterministic: P0 or P1 presence drives the verdict, P2/P3 are informational.

### Verdict Line

The last line of the Findings Index (after all finding entries) is the Verdict:

```
Verdict: safe|needs-changes|risky
```

| Verdict | Condition | Meaning |
|---------|-----------|---------|
| `safe` | No P0 or P1 findings | No blocking issues found |
| `needs-changes` | At least one P1, no P0 | Issues that should be addressed |
| `risky` | At least one P0 | Critical issues that must be resolved |

The verdict is deterministic — it follows directly from the severity of findings. Agents do not choose their verdict independently; they assign severities and the verdict follows.

### Zero-Findings Case

When an agent finds no issues:

```
### Findings Index
Verdict: safe
```

The index heading and verdict line are always present, even with no findings.

### Error Case

When an agent fails to complete its review:

```
### Findings Index
Verdict: error

Agent failed to produce findings after retry. Error: {error message}
```

Error verdicts are excluded from synthesis — they don't count toward convergence and don't affect the aggregate verdict. The orchestrator reports them as "agent failed" in the summary.

### Prose Sections

After the Findings Index, agents write human-readable prose:

1. **Summary** — 3-5 line overview of the review
2. **Issues Found** — Numbered list with severity, evidence, and explanation
3. **Improvements** — Numbered suggestions with rationale

Prose sections are not parsed by the orchestrator. They exist for human consumption and for resolving conflicts during synthesis when the orchestrator needs more context.

### Malformed Output Handling

If an agent's output doesn't start with `### Findings Index` or the index lines don't match the expected format:

1. Classify as **malformed** (not error — the agent produced output, just not in the right format)
2. Fall back to prose-based reading: extract findings from Summary and Issues sections directly
3. Report to user: "Agent {name} produced malformed index — using prose fallback"
4. Include prose-extracted findings in synthesis, but mark them with lower confidence (they weren't structured)

## Model Provenance Metadata

When agents are dispatched across multiple model providers (e.g., Claude + OpenRouter), the orchestrator records three provenance fields per agent at dispatch time:

| Field | Example | Purpose |
|-------|---------|---------|
| `provider` | `claude`, `openrouter`, `direct` | Dispatch backend — drives cost accounting and fallback routing |
| `model_family` | `claude`, `deepseek`, `qwen`, `yi` | Training lineage — drives cross-family convergence weighting |
| `model_id` | `deepseek/deepseek-chat`, `claude-sonnet-4-6` | Exact model — drives reproducibility, version pinning, per-model quality tracking |

These fields are **not part of the Findings Index text format** (agents don't write them). The orchestrator injects them into `findings.json` during synthesis based on dispatch metadata. They enable:

- **Cross-family convergence**: Agreement between agents from different `model_family` values is weighted higher (1.5x) than same-family agreement, because different training pipelines produce genuinely independent assessments.
- **Cost accounting**: `provider` and `model_id` determine per-token cost rates for the cost report.
- **Quality tracking**: Per-`model_id` finding recall and precision over time, enabling data-driven routing decisions.
- **Verification flagging**: Single-source P0/P1 findings from non-top-tier providers are flagged `verification_recommended`.

When all agents run on the same provider (single-family mode), these fields are still populated but cross-family weighting has no effect.

## interflux Reference

In interflux, the Findings Index contract is defined in `skills/flux-drive/phases/shared-contracts.md`. The synthesizer (`phases/synthesize.md`) parses indices in Step 3.1 (validation) and Step 3.2 (collection). ID prefixes follow the pattern of agent abbreviations: `AR` for architecture, `SF` for safety, `CR` for correctness, `QS` for quality, `UP` for user-product, `PF` for performance, `GD` for game-design.

## Conformance

An implementation conforming to this specification:

- **MUST** produce output starting with `### Findings Index`
- **MUST** include a `Verdict:` line after all finding entries (even if empty)
- **MUST** use severity levels `P0|P1|P2|P3` exactly as defined
- **MUST** compute verdict deterministically from severity levels
- **MUST** produce the error stub format when an agent fails
- **SHOULD** use the `[A-Z]{2,3}-\d{3}` ID format for agent attribution
- **SHOULD** handle malformed output gracefully with prose fallback
- **MAY** extend the prose section format with additional sections
- **MAY** add metadata fields to finding lines (after the Title, separated by `|`) as long as the first 4 fields remain stable
