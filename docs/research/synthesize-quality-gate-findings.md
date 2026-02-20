# Quality Gate Synthesis: Interspect Overlay System

**Date:** 2026-02-18
**Mode:** quality-gates
**Context:** 7 files changed across shell (bash) and markdown. Risk domains: security (prompt injection, sanitization), correctness (flock serialization, TOCTOU, awk state machines), architecture (single source of truth), quality (shell idioms, test robustness). 4 agents dispatched: fd-architecture, fd-safety, fd-correctness, fd-quality.

---

## Validation

4/4 agents valid. 0 failed. All four files contain a `### Findings Index` header and a `Verdict:` line.

| Agent | File | Status | Verdict |
|-------|------|--------|---------|
| fd-architecture | `.clavain/quality-gates/fd-architecture.md` | Valid | needs-changes |
| fd-safety | `.clavain/quality-gates/fd-safety.md` | Valid | needs-changes |
| fd-correctness | `.clavain/quality-gates/fd-correctness.md` | Valid | needs-changes |
| fd-quality | `.clavain/quality-gates/fd-quality.md` | Valid | needs-changes |

---

## Overall Verdict: needs-changes

All four agents returned `needs-changes`. No agent returned `safe`. No agent returned `error`. Gate: **FAIL**.

Finding counts after deduplication:
- P1 (must fix): 7
- P2 (should fix): 5
- P3/IMP (optional): 12
- Conflicts resolved: 3

---

## Deduplication Analysis

### Cross-agent convergence

The following findings were flagged by multiple agents and are deduplicated below. The most specific, technically detailed version is kept.

**Heredoc injection (S1/Q1/A4) — 3/4 agents:**
- fd-safety: command substitution execution risk in heredoc body
- fd-quality: premature heredoc termination if content contains literal `OVERLAY` on its own line
- fd-architecture: policy concern + safe-in-practice note due to upstream sanitization

All three converge on the same fix. The safety framing (S1) is most technically complete: `$evidence_ids` survives `jq type == "array"` validation but is not passed through `_interspect_sanitize`, so a JSON value containing `$(cmd)` is shell-executed on write. This is the canonical finding.

**Awk injection (Q2/S4) — 2/4 agents:**
- fd-quality: inconsistent with library patterns, practical fix (`-v` arg)
- fd-safety: integer validation before use

Both converge on the same root cause and same fix. Combined as Q2-S4.

**launch.md parser divergence (A2/S3/Q9) — 3/4 agents:**
- fd-architecture: violated "no inline frontmatter parsing" library rule
- fd-safety: re-sanitization is spec-only, no enforcement for non-library callers
- fd-quality: awk expression will drift if library implementation changes

Merged as A2-S3-Q9. Fix addresses all three concerns.

**`local` outside function (A6/S5/C-06/Q5) — 4/4 agents:**
All four agents flagged the same line (`commands/interspect-status.md:279-280`). This is the highest convergence finding in the set. It is a P2 (not P1) because the risk is at copy-paste time, not runtime (the doc is pseudocode, not an executed script).

**Rollback/tmpfile (C-01/S-I1) — 2/4 agents:**
fd-correctness raises C-01 as MEDIUM with the git-index-dirty consequence. fd-safety raises I1 as INFO focused only on PID reuse. The correctness analysis is more complete and is retained.

**set -e canary suppression (C-02/Q4) — 2/4 agents:**
fd-correctness identifies the full user-visible failure sequence (write succeeds, canary fails, caller reports total failure, user retries, hits dedup error). fd-quality flags the general `set -e` + `|| true` pattern as a documentation gap. The correctness framing is more actionable.

**TOCTOU disable (C-03/A5) — 2/4 agents:**
fd-correctness provides the concrete interleaving: second concurrent disabler's `git commit` fails → rollback runs `git restore` → overlay re-enabled. fd-architecture notes the asymmetry with the write path but says it is benign. The correctness analysis reveals it is NOT benign — the overlay can be silently re-enabled. This is a P2, not P3.

### Self-retracted findings

**Q3 (fd-quality):** Token budget `combined` variable initialisation — initially rated MEDIUM but self-retracted by the agent after closer reading. The separator logic is correct. Excluded from synthesis.

### Protected paths

`PROTECTED_PATHS` not specified; no findings discarded.

---

## P1 Findings (Must Fix Before Merge)

### 1. Unquoted heredoc shell expansion — command substitution risk [S1/Q1/A4]

**File:** `hub/clavain/hooks/lib-interspect.sh` ~line 1521
**Convergence:** 3/4 agents

The heredoc delimiter `OVERLAY` is unquoted (`<<OVERLAY` not `<<'OVERLAY'`), so bash performs variable expansion, arithmetic expansion, and command substitution on every line before writing. The specific risk vector: `$evidence_ids` is validated via `jq -e 'type == "array"'` but not sanitized through `_interspect_sanitize`. A JSON array value of `[1, $(malicious)]` survives the `jq type` check and is shell-executed when written into the file.

Additional risk (fd-quality): if any of `$content`, `$created_by`, or `$evidence_ids` contain the literal string `OVERLAY` on its own line, the heredoc terminates prematurely, producing a truncated overlay file.

The commit message construction in the same function uses `printf`/`mktemp` correctly. Apply the same pattern here.

Fix:
```bash
printf -- '---\nactive: true\ncreated: %s\ncreated_by: %s\nevidence_ids: %s\n---\n' \
    "$created" "$created_by" "$evidence_ids" > "$tmpfile"
printf '%s\n' "$content" >> "$tmpfile"
```

---

### 2. Injection filter stores [REDACTED] without rejection [S2]

**File:** `hub/clavain/hooks/lib-interspect.sh` lines 1219-1226
**Convergence:** 1/4 agents

`_interspect_sanitize` returns the string `[REDACTED]` with exit code 0 when it matches an injection pattern. The empty-content guard downstream (`if [[ -z "$content" ]]`) does not trigger. The overlay is committed to git with `[REDACTED]` as its body and injected into agent prompts. The user approved the pre-sanitized draft at proposal time (shown in `interspect-propose.md` step 4) — not `[REDACTED]`. This creates a gap between what the user approved and what is stored.

Fix:
```bash
# In _interspect_sanitize, replace the [REDACTED] branch with:
printf '%s' ""
return 1
```

Caller:
```bash
content=$(_interspect_sanitize "$content" 2000) || {
    echo "ERROR: Overlay content rejected — contains instruction-like patterns" >&2
    return 1
}
```

---

### 3. Tmpfile rollback incomplete — orphaned temp file + possible dirty git index [C-01]

**File:** `hub/clavain/hooks/lib-interspect.sh` lines 1520-1540
**Convergence:** 2/4 agents

Two rollback failure modes:
1. If `mv "$tmpfile" "$fullpath"` fails (disk full, permission error), `$tmpfile` stays on disk permanently. The rollback only removes `$fullpath` (which was never created), leaving the tmpfile stranded.
2. If `git commit` fails after a successful `mv`, rollback runs `rm -f "$fullpath"` and then `git reset HEAD -- "$rel_path" 2>/dev/null || true`. If `git reset` fails (locked index, detached HEAD), the file is gone from the working tree but still staged — the next unrelated commit accidentally includes the overlay.

Fix:
```bash
# Add at the top of _interspect_write_overlay_locked, after local vars:
trap 'rm -f "$tmpfile"' EXIT

# And for the git reset failure:
if ! git reset HEAD -- "$rel_path"; then
    echo "ERROR: Rollback incomplete — overlay staged but not on disk. Run: git reset HEAD -- $rel_path" >&2
fi
```

---

### 4. `set -e` inside locked function — canary failure masquerades as write failure [C-02]

**File:** `hub/clavain/hooks/lib-interspect.sh` lines 1485-1603
**Convergence:** 2/4 agents

The locked function sets `set -e`. The `if ! sqlite3 ... INSERT INTO canary` correctly prevents `set -e` from triggering on the INSERT. However, the `sqlite3 UPDATE modifications SET status = 'applied-unmonitored'` inside the `then` branch is unprotected. If the UPDATE fails (e.g., DB locked by a concurrent reader), `set -e` fires and the function exits non-zero. The caller reports "ERROR: Could not write overlay" even though the overlay was successfully committed to git.

User-visible failure sequence:
1. Overlay write succeeds — file committed, modifications row inserted
2. `INSERT INTO canary` fails (DB locked)
3. `UPDATE modifications` also fails (DB still locked)
4. `set -e` fires, function exits non-zero
5. Caller: "ERROR: Could not write overlay"
6. User retries → hits "ERROR: Overlay {id} already exists for {agent}"
7. Overlay is active and unmonitored; no diagnostic

Fix:
```bash
if ! sqlite3 "$db" "INSERT INTO canary ..."; then
    sqlite3 "$db" "UPDATE modifications SET status = 'applied-unmonitored' ..." 2>/dev/null || true
    echo "WARN: Canary monitoring failed — overlay active but unmonitored." >&2
fi
# Ensure commit_sha is always returned after a successful commit:
echo "$commit_sha"
```

---

### 5. `launch.md` inlines awk YAML parser — violation of library's single-source-of-truth rule [A2/S3/Q9]

**File:** `plugins/interflux/skills/flux-drive/phases/launch.md` line 78
**Convergence:** 3/4 agents

The library comment at line 1152 states: "All overlay code MUST use these helpers — never parse frontmatter inline." The launch spec duplicates the awk expression:
```
awk '/^---$/ { if (++delim == 2) exit } delim == 1 && /^active: true$/ { found=1 } END { exit !found }'
```

It also inlines re-sanitization as a string match rather than calling `_interspect_sanitize`. If the YAML delimiter logic or injection-pattern list changes in the library, the launch spec silently diverges. The re-sanitization in the spec is prose guidance to the LLM agent — there is no enforcement that the agent will actually perform this step or that its pattern matching will be equivalent to the library function.

Fix: Change step 2.1d to instruct the agent to call `_interspect_overlay_is_active "$overlay_file"` and `_interspect_sanitize "$body"` (library must be sourced). If the library cannot be called in the spec context, add an explicit maintenance callout naming the library function and requiring sync.

---

### 6. Awk injection via unquoted `word_count` interpolation [Q2/S4]

**File:** `hub/clavain/hooks/lib-interspect.sh` ~line 1380
**Convergence:** 2/4 agents

```bash
word_count=$(printf '%s' "$content" | wc -w | tr -d ' ')
awk "BEGIN { printf \"%d\", ${word_count} * 1.3 }"
```

`word_count` is interpolated directly into the awk program string. `wc -w | tr -d ' '` normally produces a digit string, but on unusual locales or malformed pipes the output could contain characters that alter the awk program. Pattern is inconsistent with the rest of the library which avoids dynamic string injection into interpreters.

Fix:
```bash
if ! [[ "$word_count" =~ ^[0-9]+$ ]]; then
    echo "0"
    return 0
fi
awk -v wc="$word_count" 'BEGIN { printf "%d", wc * 1.3 }'
```

---

### 7. `_interspect_flock_git` API contract undocumented for function-as-command pattern [A1]

**File:** `hub/clavain/hooks/lib-interspect.sh` lines 1534-1537 and 1141-1158
**Convergence:** 1/4 agents

`_interspect_flock_git` is documented as executing a git command ("Usage: `_interspect_flock_git git add <file>`"). The new code passes a shell function name as the first argument:

```bash
flock_output=$(_interspect_flock_git _interspect_write_overlay_locked \
    "$root" "$rel_path" ...)
```

This works because `_interspect_flock_git` calls `"$@"` which can invoke shell functions defined in the sourced library. However, a future maintainer who wraps `_interspect_flock_git` in a subprocess (e.g., `$(...)`) would silently break the function-call pattern since shell functions are not exported unless `export -f` is used.

Fix: Update the function's comment block to document that it accepts any command or shell function name; note that shell functions must be defined in the sourced library (not a subshell).

---

## P2 Findings (Should Fix)

### 8. TOCTOU in `_interspect_disable_overlay` can re-enable a just-disabled overlay [C-03/A5]

**File:** `hub/clavain/hooks/lib-interspect.sh` lines 1634-1637
**Convergence:** 2/4 agents

Pre-flock active check reads `active: true` for both concurrent callers. Both enter the lock. The second caller's `git commit` fails ("nothing to commit") → rollback runs `git restore` → file restored to `active: true`. Overlay is re-enabled silently with no error visible to the first disabler.

Fix: Repeat the active check inside `_interspect_disable_overlay_locked`; exit cleanly if already inactive.

---

### 9. `local` keyword outside function body in `interspect-status.md` pseudocode [A6/S5/C-06/Q5]

**File:** `commands/interspect-status.md` lines 279-280
**Convergence:** 4/4 agents — highest convergence in the set

```bash
local escaped_agent
escaped_agent=$(_interspect_sql_escape "$agent")
```

In bash, `local` outside a function body produces a warning and behaves as an unscoped variable. The other command docs (`interspect-revert.md`, `interspect-propose.md`) do not use `local` outside function contexts.

Fix: Remove `local` from this pseudocode block, or annotate that the snippet requires a surrounding function body.

---

### 10. Test suite `set -euo pipefail` exits on first failure, defeating FAIL accumulator [Q7]

**File:** `hub/clavain/test-interspect-overlay.sh` line 8, lines 320-331
**Convergence:** 1/4 agents

The `fail()` function increments `FAIL` and records the test name, intending to accumulate failures and print a summary. But `set -e` at the top level aborts the script on any unchecked non-zero exit before `fail()` is called. Test 12 calls `_interspect_overlay_body` inside an `if` block — if that function fails under `set -e`, the script exits before recording the failure.

Fix: Remove `set -e` from the top-level (keep `set -uo pipefail`), or use per-test `( subshell )` isolation.

---

### 11. `echo "$evidence_ids"` for jq validation — leading-hyphen flag risk [Q8]

**File:** `hub/clavain/hooks/lib-interspect.sh` ~line 1258
**Convergence:** 1/4 agents

`echo` with values beginning with `-` may be interpreted as flags on some shells. The existing library uses `printf '%s'` consistently for this purpose.

Fix: `printf '%s\n' "$evidence_ids" | jq -e 'type == "array'`

---

### 12. Multi-line content in $6 — trailing newline stripping on subshell output [C-04]

**File:** `hub/clavain/hooks/lib-interspect.sh` lines 1487-1489
**Convergence:** 1/4 agents

`flock_output=$( ... )` strips trailing newlines from the subshell's stdout. If anything in the locked function's output path writes trailing newlines before the commit SHA, `tail -1` may not correctly recover the SHA. Low-probability in practice (commit SHA has no trailing newline from `git commit --format=%H`), but worth documenting.

---

## P3 / IMP — Optional Improvements

| ID | Agent | Description |
|----|-------|-------------|
| A7 | fd-architecture | Remove redundant `_interspect_redact_secrets` call — already called inside `_interspect_sanitize`. Adds ~8 sed passes overhead. |
| A3 | fd-architecture | Document that `_interspect_read_overlays` is safe to call inside flock (read-only, no lock acquisition). Prevents future maintainer from assuming nesting deadlock. |
| C-05 | fd-correctness | Document CWD interaction between `cd "$root"` and `git rev-parse` inside flock. |
| C-07 | fd-correctness | Handle files with zero frontmatter delimiters in awk state machine gracefully (currently exits with found=0, which is correct but undocumented). |
| C-08 | fd-correctness | Rollback after git commit failure leaves DB in written state if `modifications` INSERT succeeded before error. Add documentation or compensating cleanup. |
| C-09 | fd-correctness | Launch-time budget check reads overlays outside flock — tokens could momentarily exceed 500 during concurrent write. Document as known limitation or move check inside the lock. |
| I1 | fd-safety, fd-correctness | Use `mktemp` in the same directory instead of PID-based temp file naming for explicit atomicity. |
| I2 | fd-safety | Add comment noting `git commit --no-verify` is intentional, compensated by sanitization pipeline. |
| Q10 | fd-quality | Extend agent name validator tests: add empty string, path traversal, and shell metachar cases to match depth of overlay ID validation tests. |
| Q11 | fd-quality | Move the 500-token budget constant from 3 hardcoded locations to `confidence.json` as `overlay_token_budget` field. |
| I2-arch | fd-architecture | Extract overlay file frontmatter construction into `_interspect_format_overlay_file` helper to give the format a single definition point. |
| I3-arch | fd-architecture | Add new public overlay functions to the library's top-of-file comment block for discoverability. |

---

## Conflicts and Disagreements

### Heredoc severity framing
- fd-architecture (A4): policy concern — the CLAUDE.md heredoc rule applies to Claude Code Bash tool calls, not library source files; notes it is safe in practice due to upstream sanitization.
- fd-safety (S1): concrete exploit path — `$evidence_ids` is not sanitized; JSON `[1, $(cmd)]` survives jq type-check and executes on write.
- fd-quality (Q1): premature termination risk — content containing literal `OVERLAY` on its own line truncates the heredoc.

Resolution: The safety agent's analysis is most technically complete and most conservative. Treat as P1. The architecture agent's "safe in practice" note is factually accurate for `$content` and `$created_by` (which are sanitized), but not for `$evidence_ids`.

### C-01 vs I1 severity
- fd-correctness (C-01): MEDIUM — identifies the git-index-dirty consequence where `git reset HEAD` failure leaves the file staged, causing accidental inclusion in the next commit.
- fd-safety (I1): INFO — notes PID reuse is not a vulnerability in this context.

Resolution: The correctness analysis reveals a real data-integrity bug (silent overlay in the next commit). Retain as P1.

### C-03/A5 — "benign" vs "not benign"
- fd-architecture (A5): calls the concurrent disable race benign — the second writer does extra work but produces correct output.
- fd-correctness (C-03): provides the concrete interleaving showing the second writer's `git commit` fails → rollback runs `git restore` → overlay re-enabled.

Resolution: The correctness analysis is more detailed and reveals the race is not benign. The architecture agent missed the rollback consequence. Retain as P2.

### Q3 self-retraction
fd-quality initially rated Q3 (token budget `combined` separator) MEDIUM, then retracted it after closer analysis. Excluded from synthesis.

---

## Summary for Gate Decision

**Gate: FAIL**

7 P1 findings must be resolved before merge. The two most critical:
1. **Unquoted heredoc (S1/Q1/A4):** `$evidence_ids` is not sanitized before shell expansion — concrete command execution path via crafted JSON array value. Convergence 3/4 agents.
2. **TOCTOU disable race (C-03):** Concurrent disable can silently re-enable an overlay via git rollback. Convergence 2/4 agents.

The overlay system is architecturally sound (awk state machines, flock serialization, path containment, compound group_id, defense-in-depth sanitization are all correct). All findings are fixable without structural changes. The implementation demonstrates careful design; the issues are in exception paths and integration points between components.
