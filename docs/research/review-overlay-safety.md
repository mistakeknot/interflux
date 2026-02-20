# Safety Review: interspect Overlay System (Full Analysis)
**Reviewer:** fd-safety (Flux-drive Safety Reviewer)
**Date:** 2026-02-18
**Primary output:** /root/projects/Interverse/.clavain/quality-gates/fd-safety.md

---

## System Overview and Threat Model

The interspect overlay system is a Type 1 self-modification mechanism: LLM agents that perform reviews generate prompt tuning instructions ("overlays") based on observed patterns of agent errors. Those overlays are stored as markdown files with YAML frontmatter under `.clavain/interspect/overlays/<agent>/`, committed to git, and injected into future agent prompts at flux-drive launch time.

**This system sits at an unusually high-risk intersection of concerns:**
- Untrusted content (LLM-generated text, user-provided inputs, database evidence context) flows through a write pipeline into files
- Those files are then read back and injected directly into LLM agent system prompts
- The injection increases the surface area for prompt injection: content that causes an agent to behave incorrectly could compound across all future reviews

The system is local-only (no network exposure, no external callers). Credentials are stored externally; the overlay files themselves do not contain credentials. The deployment path is git-commit-based with user approval via `AskUserQuestion`. The operator (the user) is the only party who approves overlay creation and reverts.

**Risk classification: HIGH** — the write→inject pipeline has a prompt injection vector with compounding behavioral impact.

---

## Architecture Walk-Through

### Write Pipeline

1. `interspect-propose.md` orchestrates overlay creation. The LLM agent queries evidence from SQLite, drafts content, calls `_interspect_sanitize` on the draft, presents the sanitized draft to the user via `AskUserQuestion`, and calls `_interspect_write_overlay` on accept.

2. `_interspect_write_overlay` (lib-interspect.sh:1402-1482):
   - Validates agent name via regex `^fd-[a-z][a-z0-9-]*$`
   - Validates overlay ID via regex `^[a-z0-9][a-z0-9-]*$`
   - Validates evidence_ids is a JSON array (via jq)
   - Sanitizes content through `_interspect_sanitize` (ANSI strip, control-char strip, 2000-char truncation, secret redaction, LLM-pattern detection)
   - Runs `_interspect_redact_secrets` a second time on content
   - Assembles path from validated components + containment assertion
   - Checks path against `_interspect_validate_target` (allowlist/blocklist)
   - Writes commit message to temp file (no shell injection)
   - All further operations inside `_interspect_flock_git` (flock serialization)

3. `_interspect_write_overlay_locked` (lib-interspect.sh:1485-1675):
   - Dedup check: rejects if file already exists
   - Token budget check: reads all existing overlays, estimates combined tokens, rejects if > 500
   - Writes overlay file via heredoc + atomic mv
   - Git add + commit --no-verify
   - Rollback on git failure (rm file + git reset)
   - DB inserts for modifications and canary tables

### Read and Inject Pipeline

1. `_interspect_read_overlays` (lib-interspect.sh:1340-1368):
   - Validates agent name
   - Resolves overlay directory from git root
   - Reads all `.md` files in agent directory, sorted alphabetically
   - For each: calls `_interspect_overlay_is_active` (awk state machine)
   - If active, calls `_interspect_overlay_body` (awk state machine)
   - Concatenates non-empty bodies

2. `launch.md` Step 2.1d (launch.md:72-87):
   - Calls `_interspect_read_overlays` (or equivalent inline awk)
   - **Re-sanitizes content before injection** (prose spec, not enforced code)
   - Appends `{overlay_content}` into the "Overlay Context" section of each agent's prompt

### YAML Parsing

Both `_interspect_overlay_is_active` and `_interspect_overlay_body` use awk delimiter state machines that count `---` delimiters. This correctly handles:
- Body content containing literal `active: true`
- Body content containing `---` (horizontal rules in markdown)
- Missing or malformed frontmatter (returns false/empty correctly)

This is the correct implementation. Naive grep-based parsing would fail on these cases.

### Git Serialization

`_interspect_flock_git` uses `flock -w 30` on `.clavain/interspect/.git-lock`. The budget check, file write, git commit, and DB inserts all happen inside a single flock acquisition, making them TOCTOU-safe as a group. This is the correct architecture.

### SQL Escaping

`_interspect_sql_escape` handles single-quote doubling, backslash escaping, and control-character stripping. It is consistently applied before all SQL interpolations in the overlay code. No prepared statement API is available (sqlite3 CLI), so this manual escaping approach is correct and consistently applied.

---

## Security Findings

### S1 (MEDIUM): Unquoted heredoc expands shell variables into overlay file body

**File:** `/root/projects/Interverse/hub/clavain/hooks/lib-interspect.sh` lines 1521-1529

```bash
cat > "$tmpfile" <<OVERLAY
---
active: true
created: ${created}
created_by: ${created_by}
evidence_ids: ${evidence_ids}
---
${content}
OVERLAY
```

The heredoc delimiter `OVERLAY` is not quoted. Bash performs full variable expansion, arithmetic expansion `$((...))`, and command substitution `$(...)` on every line during heredoc processing.

**Attack scenario:** An `evidence_ids` value of `[1, $(id)]` would pass the `jq -e 'type == "array"'` validation check (jq sees this as syntactically invalid and would reject it, but the jq check is done on the raw string `echo "$evidence_ids" | jq -e 'type == "array"'` — if evidence_ids contains `]` followed by a newline and a new valid JSON array, or if jq's parsing context allows partial matches, there could be edge cases). More practically, `evidence_ids` is not run through `_interspect_sanitize`, so it does not go through the control-character or LLM-pattern filters that `$content` does.

**Impact:** At worst, command execution during file write; at best, corrupted YAML frontmatter that breaks overlay parsing or inserts unexpected content the user did not review.

**Mitigation:** Quote the heredoc delimiter (`<<'OVERLAY'`) and use explicit printf-based field interpolation for the dynamic fields. Since content must remain dynamic, use a two-step write:

```bash
printf -- '---\nactive: true\ncreated: %s\ncreated_by: %s\nevidence_ids: %s\n---\n' \
    "$created" "$created_by" "$evidence_ids" > "$tmpfile"
printf '%s\n' "$content" >> "$tmpfile"
```

Note that `$created_by` and `$evidence_ids` should also be sanitized through `_interspect_sql_escape` or `_interspect_sanitize` before being placed into the YAML frontmatter to prevent frontmatter injection (e.g., `created_by: foo\nactive: false` overriding the active field).

---

### S2 (MEDIUM): Injection filter returns [REDACTED] and allows write to proceed with neutered content

**File:** `/root/projects/Interverse/hub/clavain/hooks/lib-interspect.sh` lines 1216-1226

```bash
if [[ "$lower" == *"<system>"* ]] || ... ; then
    printf '%s' "[REDACTED]"
    return 0
fi
```

When `_interspect_sanitize` detects an injection pattern, it returns the string `[REDACTED]` and exits with code 0. In `_interspect_write_overlay`:

```bash
content=$(_interspect_sanitize "$content" 2000)
content=$(_interspect_redact_secrets "$content")
if [[ -z "$content" ]]; then
    echo "ERROR: Overlay content is empty after sanitization" >&2
    return 1
fi
```

`[REDACTED]` is non-empty, so the guard passes. The overlay file `[REDACTED]` is committed to git and injected into agents.

**Additional concern:** The propose command (interspect-propose.md step 4) shows the user the pre-write-call sanitized content for approval. If the user approves "focus on auth patterns" but the string somehow contains a matched pattern at write time (perhaps after user edit or parameter substitution), the user-approved content diverges from the stored content silently.

**Mitigation:** Change the filter to signal rejection clearly:

```bash
# Return empty string to trigger existing empty-content guard
printf '%s' ""
return 0
```

Or even better, return a non-zero exit and handle it in the caller:

```bash
return 1   # signal rejection; caller should check $?
```

Update the caller:
```bash
content=$(_interspect_sanitize "$content" 2000) || {
    echo "ERROR: Overlay content contains instruction-injection patterns and was rejected." >&2
    return 1
}
```

---

### S3 (LOW): Injection re-sanitization at launch time is spec instruction, not enforced code

**File:** `/root/projects/Interverse/plugins/interflux/skills/flux-drive/phases/launch.md` line 80

The spec instructs the agent executing flux-drive launch to re-sanitize overlay bodies before injection. This is sound defense-in-depth design (it protects against hand-edited overlays that bypass write-time sanitization). However, the check lives only in prose documentation; it is not enforced by a library function.

The risk is residual: it depends on the agent faithfully implementing the spec check with equivalent pattern coverage. If the agent skips the step, a hand-edited overlay containing `ignore previous instructions` would be injected without filtering.

**Mitigation:** Make `_interspect_read_overlays` apply the sanitize pipeline to each overlay body before returning it. Since `_interspect_read_overlays` is the single authoritative read path, this converts a documentation requirement into an enforced code property:

```bash
body=$(_interspect_overlay_body "$overlay_file")
body=$(_interspect_sanitize "$body" 2000) || {
    echo "WARN: Overlay $(basename "$overlay_file") skipped — injection pattern detected." >&2
    continue
}
```

---

### S4 (LOW): `word_count` is shell-interpolated into awk program string without integer validation

**File:** `/root/projects/Interverse/hub/clavain/hooks/lib-interspect.sh` lines 1377-1381

```bash
word_count=$(printf '%s' "$content" | wc -w | tr -d ' ')
awk "BEGIN { printf \"%d\", ${word_count} * 1.3 }"
```

`wc -w | tr -d ' '` reliably produces a clean integer on standard Linux. However, the awk program is built by string interpolation, so if `word_count` were ever non-numeric (e.g., due to a locale-aware `wc` producing `1,234` with a comma separator, or an error message on a failing pipeline with `set -e` not active here), the awk command would be malformed or silently compute 0.

**Mitigation:** Add integer validation:

```bash
if ! [[ "$word_count" =~ ^[0-9]+$ ]]; then
    echo "0"
    return 0
fi
```

---

### S5 (LOW): `local` keyword in loop body of command-spec pseudocode outside function context

**File:** `/root/projects/Interverse/commands/interspect-status.md` lines 279-280

```bash
local escaped_agent
escaped_agent=$(_interspect_sql_escape "$agent")
```

This snippet appears inside a `for agent_dir in ...` loop in the Active Overlays section of the status command. The `local` keyword is valid only inside bash functions. When an agent implements this spec snippet at the top level (outside a function), bash will emit a warning and `local` becomes a no-op — the variable leaks to the enclosing scope, which may cause the `agent` loop variable to be corrupted if the command is sourced.

**Mitigation:** Remove `local` from loop-body pseudocode, or annotate clearly that this pattern requires the surrounding code to be inside a function definition.

---

## Deployment and Operational Safety

### Rollback feasibility

Overlay disable (`_interspect_disable_overlay`) toggles `active: false` in the YAML frontmatter and commits the change. The original overlay content remains in git history. Rolling back:
- To a prior state: `git revert <commit_sha>` (commit SHA is stored in the DB)
- To disable immediately: `/interspect:revert <agent>` (tested in test-interspect-overlay.sh)

Both paths are exercised by tests 15-18. Rollback is feasible and practiced.

### Partial failure handling

The write path has a rollback on git commit failure:
```bash
rm -f "$fullpath"
git reset HEAD -- "$rel_path" 2>/dev/null || true
```

The disable path restores from git:
```bash
git restore "$rel_path" 2>/dev/null || git checkout -- "$rel_path" 2>/dev/null || true
```

DB records are written after the git commit inside the same flock. If DB insert fails after a successful git commit, the overlay is active in git but the `modifications` row shows `applied-unmonitored` (for canary failure). This is the correct soft-fail behavior — the overlay works but lacks canary monitoring.

### Token budget

The 500-token budget check happens inside the flock, making it TOCTOU-safe. The heuristic `word_count * 1.3` will undercount for code snippets (tokens are more dense than words for identifiers) but the 500-token limit is conservative relative to typical overlay sizes (~50-100 words).

### Canary monitoring

Each overlay creates a canary record. The canary tracks use counts (window: 20 uses) and time (14-day expiry). The status command surfaces canary state. This is a sound operational control for detecting regressions introduced by overlays.

---

## What Is Done Well

- **Path containment** is multi-layer: agent name regex prevents `../` before path construction, overlay ID regex prevents traversal, string containment assertion (`case "$fullpath" in "${overlays_root}"*`) catches any residual escape, and `_interspect_validate_target` checks the allowlist.
- **YAML state machine parsers** are correct and are centralized as the single source of truth (no inline parsing in callers).
- **Flock serialization** is comprehensive — budget check, write, git commit, and DB insert are atomic under a single lock acquisition.
- **SQL escaping** is consistent — every field that flows into a SQL string goes through `_interspect_sql_escape`.
- **Test coverage** is thorough for the happy path and the main edge cases (inactive overlay, body with `---`, path traversal, budget, dedup, sanitization rejection, DB records, disable idempotency).

---

## Summary of Required Changes

| Priority | Issue | Change Required |
|----------|-------|----------------|
| Fix | S1 (MEDIUM) | Quote heredoc delimiter; sanitize frontmatter fields before writing |
| Fix | S2 (MEDIUM) | Change injection filter to return empty or non-zero; update caller guard |
| Recommended | S3 (LOW) | Apply sanitize in `_interspect_read_overlays` rather than relying on spec prose |
| Recommended | S4 (LOW) | Validate `word_count` is integer before awk interpolation |
| Cleanup | S5 (LOW) | Remove `local` from loop-body pseudocode in interspect-status.md |
