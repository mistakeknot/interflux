# Completion Signal

> flux-drive-spec 1.0 | Conformance: Core

## Overview

The Completion Signal contract defines how agents communicate their state to the orchestrator. The orchestrator doesn't have visibility into agent internals — it can only observe the filesystem. This contract uses a simple atomic rename pattern: agents write to a `.partial` file, then rename to `.md` when done. The orchestrator polls for `.md` files to detect completion.

## Specification

### Write Flow

Agents follow this exact sequence:

1. **Begin writing** to `{OUTPUT_DIR}/{agent-name}.md.partial`
2. **Produce output** — Findings Index, prose sections, all content
3. **Append sentinel** as the last line: `<!-- flux-drive:complete -->`
4. **Rename** `.md.partial` → `.md` (atomic on POSIX filesystems)

```
Agent starts  →  writes to foo.md.partial  →  appends sentinel  →  renames to foo.md
                                                                         ↑
                                                            Orchestrator detects this
```

> **Why this works:** The atomic rename guarantees the orchestrator never reads a partially-written file. The sentinel comment provides a secondary validation that the agent finished intentionally (not crashed mid-write). Together they give the orchestrator two signals: "file exists" (rename happened) and "content is complete" (sentinel present).

### Orchestrator Monitoring

The orchestrator polls the output directory for completion:

| Parameter | Default | Description |
|-----------|---------|-------------|
| Poll interval | 30 seconds | How often to check for new `.md` files |
| Timeout (local agents) | 5 minutes | Maximum wait for locally-dispatched agents |
| Timeout (remote agents) | 10 minutes | Maximum wait for remotely-dispatched agents (e.g., cross-AI) |

On each poll cycle, the orchestrator:

1. Lists `{OUTPUT_DIR}/*.md` files (not `.partial`)
2. Counts completed agents: `[N/M agents complete]`
3. Reports each new completion with elapsed time
4. Checks if N equals M (all done) → proceed to synthesis

### Timeout Behavior

When an agent exceeds the timeout:

1. Check if `.partial` file exists:
   - **Yes**: Agent produced partial output. Read the `.partial` file, classify as **malformed** (no sentinel), and include in synthesis with lower confidence.
   - **No**: Agent produced nothing. Generate an error stub (see Findings Index contract) and write it as `{agent-name}.md`.
2. Report to user: "Agent {name} timed out after {timeout}s"
3. Continue with synthesis using available results

> **Why this works:** Timeouts are graceful, not fatal. The orchestrator degrades smoothly — a timed-out agent is just one fewer data point, not a system failure. Partial output is still valuable; it might contain findings that completed successfully before the timeout.

### Error Stub Generation

When an agent fails (timeout, crash, or explicit error), the orchestrator writes an error stub to `{OUTPUT_DIR}/{agent-name}.md`:

```markdown
### Findings Index
Verdict: error

Agent failed to produce findings after retry. Error: {error description}
```

Error stubs ensure every launched agent has exactly one `.md` file in the output directory. This invariant simplifies synthesis: the synthesizer always processes exactly N files for N launched agents.

### Retry Policy

Before generating an error stub, the orchestrator may retry the agent:

1. First failure → retry once with the same prompt
2. Second failure → generate error stub, do not retry again

Retry is optional and implementation-specific. The contract only requires that:
- Every launched agent eventually has a `.md` file
- Failed agents get an error stub with `Verdict: error`

### Partial Completion Edge Cases

| Scenario | Orchestrator Action |
|----------|-------------------|
| `.partial` exists, has sentinel | Agent renamed failed. Treat as complete (copy to `.md`). |
| `.partial` exists, no sentinel | Agent timed out mid-write. Use partial content as malformed output. |
| `.partial` exists, empty | Agent started but produced nothing. Generate error stub. |
| No `.partial`, no `.md` | Agent never started. Generate error stub. |
| `.md` exists, no sentinel | Agent used a different completion mechanism. Accept but log warning. |

## Interflux Reference

In Interflux, completion monitoring is implemented in `skills/flux-drive/phases/launch.md` (Step 2.3). The implementation-level contract details are in `skills/flux-drive/phases/shared-contracts.md`. Local agents are dispatched via Claude Code's `Task` tool with `run_in_background: true`; remote agents (Oracle/Codex) are dispatched via CLI tools. The orchestrator uses `Bash(ls {OUTPUT_DIR}/*.md 2>/dev/null | wc -l)` for polling.

## Conformance

An implementation conforming to this specification:

- **MUST** write agent output to `.partial` files during work, then rename to `.md` on completion
- **MUST** append `<!-- flux-drive:complete -->` sentinel before renaming
- **MUST** ensure exactly one `.md` file per launched agent after synthesis begins (via error stubs)
- **MUST** implement a timeout mechanism to prevent indefinite blocking
- **SHOULD** poll at regular intervals (default 30s) rather than using event-based detection
- **SHOULD** retry failed agents at least once before generating error stubs
- **SHOULD** handle partial output from timed-out agents gracefully
- **MUST NOT** read `.partial` files for synthesis — only process `.md` files (partial content is for timeout recovery only)
- **MUST NOT** block indefinitely waiting for completion — a timeout mechanism is required
- **MUST NOT** skip error stub generation for failed agents (every launched agent must have exactly one `.md` file)
- **MAY** use different timeout values for different agent types
- **MAY** implement event-based detection (e.g., inotify) alongside or instead of polling
