# Knowledge Lifecycle

> flux-drive-spec 1.0 | Conformance: Extension

## Overview

The Knowledge Lifecycle extension gives flux-drive a memory. Instead of treating each review as independent, the orchestrator accumulates durable patterns — verified findings that recur across reviews — and injects them into future agent prompts as context. This makes agents smarter over time without retraining. The lifecycle includes provenance tracking (to prevent false-positive feedback loops) and temporal decay (to prevent stale knowledge from biasing reviews).

## Specification

### Knowledge Entry Format

Each knowledge entry is a markdown file with YAML frontmatter:

```yaml
---
lastConfirmed: 2026-02-12
provenance: independent
---
Auth middleware often swallows context cancellation errors — check for
ctx.Err() after upstream calls in middleware/*.go.

Evidence: middleware/auth.go:47-52, handleRequest() — context.Err() not
checked after upstream call.
Verify: grep for ctx.Err() after http.Do() calls in middleware/*.go.
```

### Frontmatter Fields

| Field | Type | Values | Purpose |
|-------|------|--------|---------|
| `lastConfirmed` | ISO date | `YYYY-MM-DD` | Last time this finding was independently re-observed |
| `provenance` | enum | `independent` or `primed` | Whether the confirming agent had this entry in context |

### Body Requirements

Every knowledge entry must contain:

1. **Finding description** (1-3 sentences): The pattern or issue, phrased as a generalized heuristic
2. **Evidence anchors**: File paths, symbol names, line ranges — concrete pointers
3. **Verification steps** (1-3 steps): How to confirm the finding is still valid

> **Why this works:** Evidence anchors are what separate knowledge from folklore. An entry that says "auth middleware has a bug" rots into an unverifiable rumor. An entry that says "middleware/auth.go:47 — context.Err() not checked after http.Do()" can be mechanically verified. The verification steps make decay checking possible.

### Provenance Tracking

The `provenance` field exists to prevent a specific failure mode: the **false-positive feedback loop**.

```text
Finding compounded → injected into next review → agent re-confirms (primed)
→ lastConfirmed updated → entry never decays → false positive lives forever
```

Two provenance types break this loop:

| Provenance | Meaning | Effect on Decay |
|------------|---------|-----------------|
| `independent` | Agent flagged this WITHOUT seeing the knowledge entry | Refreshes `lastConfirmed` — genuine re-confirmation |
| `primed` | Agent had this entry in its context when it re-flagged it | Does NOT refresh `lastConfirmed` — not a true confirmation |

> **Why this works:** If an agent only re-confirms a finding because it was told about the finding, that's not evidence the issue still exists — it's confirmation bias. Only independent re-discovery (agent found the same issue without prompting) counts as genuine confirmation. This is the same logic as independent replication in scientific research.

### Temporal Decay

Knowledge entries that aren't independently confirmed decay over time:

- An entry not independently confirmed in **10 reviews** gets archived
- "10 reviews" means 10 flux-drive runs on the same project where the entry was injected into at least one agent's context
- Archived entries are moved to a designated archive directory (e.g., `knowledge/archive/`)
- Archive preserves the full entry for future reference — decay is reversible

The decay counter resets when:
- An agent independently re-discovers the finding (`provenance: independent`)
- A user manually confirms the entry (sets `lastConfirmed` to today)

> **Why this works:** 10 reviews is a generous window. If a finding was real, at least one agent should independently notice it within 10 runs. If none do, the finding is likely either fixed or was a false positive. Archiving (not deleting) preserves institutional memory — an archived entry can be promoted back if the pattern recurs.

### Accumulation

New knowledge entries are created during the synthesis phase (Phase 3) when findings meet the compounding threshold:

1. After synthesis completes, the orchestrator identifies findings that:
   - Were flagged by 2+ agents independently (high convergence)
   - Represent a durable pattern (not a one-time issue)
   - Don't duplicate an existing knowledge entry
2. For each candidate:
   - Extract the finding description, evidence, and verification steps
   - Assign `provenance: independent` (it was just discovered)
   - Set `lastConfirmed` to today
   - Write as a new knowledge entry file

The compounding step runs as a background task after the user receives their review results — it doesn't block the review flow.

### Sanitization Rules

Knowledge entries must be phrased as **generalized heuristics**, not project-specific facts:

- **Never store:** file paths to specific repos (outside the host project), hostnames, internal endpoints, organization names, customer identifiers, secrets, vulnerability details with exploitable specifics
- **Good:** "Auth middleware often swallows context cancellation errors — check for ctx.Err() after upstream calls"
- **Bad:** "middleware/auth.go in Project X has a bug at line 47"

### Retrieval

Knowledge is retrieved during Phase 2 (Launch) and injected into agent prompts:

1. **Query construction:** Combine the agent's domain keywords with the document summary from Phase 1
2. **Search:** Use semantic search (vector similarity) against the knowledge store
3. **Cap:** Maximum 5 entries per agent — more adds noise without improving review quality
4. **Injection:** Matched entries are included in the agent's prompt as a "Knowledge Context" block
5. **Timing:** Retrieval is pipelined with agent launch preparation (not during triage)

If the semantic search system is unavailable, agents run without knowledge injection. This is a graceful degradation — the review still works, it's just less informed.

> **Why this works:** 5 entries per agent is the practical limit where knowledge adds value. Beyond 5, agents start paying more attention to knowledge entries than to the actual document being reviewed. Semantic search (over keyword matching) finds conceptually related entries even when the wording differs.

### Manual Operations

- **Retraction:** Delete the knowledge entry file. No special commands needed.
- **Confirmation:** Edit the frontmatter — set `lastConfirmed` to today, `provenance` to `independent`.
- **Review all:** List files in the knowledge directory, inspect frontmatter for decay status.

## Interflux Reference

In Interflux, knowledge entries live in `config/flux-drive/knowledge/*.md`. The lifecycle rules are documented in `config/flux-drive/knowledge/README.md` (79 lines). Retrieval uses the qmd MCP server for semantic search (`mcp__plugin_interflux_qmd__vsearch`). Knowledge injection happens in `skills/flux-drive/phases/launch.md` (Step 2.1). Content routing rules that affect knowledge injection are in `skills/flux-drive/phases/slicing.md`.

Archive directory: `config/flux-drive/knowledge/archive/`. Currently 6 active knowledge entries in the Interflux reference implementation.

## Conformance

An implementation conforming to this extension:

- **MUST** track provenance (independent vs. primed) on all knowledge entries
- **MUST** implement temporal decay (configurable review count, default 10)
- **MUST** distinguish independent re-discovery from primed re-confirmation
- **MUST** include evidence anchors and verification steps in entries
- **SHOULD** use semantic retrieval for knowledge injection
- **SHOULD** cap knowledge injection at 5 entries per agent
- **SHOULD** implement sanitization rules to prevent project-specific leakage
- **MUST NOT** refresh `lastConfirmed` on primed re-confirmations (breaks the false-positive feedback loop prevention)
- **MUST NOT** delete decayed entries — archive them instead (decay is reversible)
- **MUST NOT** inject more than the configured cap of knowledge entries per agent (default 5 — more adds noise)
- **MAY** use different decay periods (10 reviews is the reference default)
- **MAY** implement knowledge compounding as a background or foreground task
- **MAY** support manual confirmation and retraction workflows
