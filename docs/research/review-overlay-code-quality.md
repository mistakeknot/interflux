# Quality Review: Interspect Overlay System (Full Analysis)

**Reviewer:** fd-quality (flux-drive)
**Date:** 2026-02-18
**Files reviewed:**
- `hub/clavain/hooks/lib-interspect.sh` — overlay section added (~406 lines of new Shell)
- `hub/clavain/test-interspect-overlay.sh` — integration test suite (42 tests)
- `hub/clavain/commands/interspect-propose.md` — overlay proposal section
- `hub/clavain/commands/interspect-revert.md` — overlay revert section
- `hub/clavain/commands/interspect-status.md` — overlay status section
- `plugins/interflux/skills/flux-drive/phases/launch.md` — overlay injection step

**Findings written to:** `/root/projects/Interverse/.clavain/quality-gates/fd-quality.md`

---

## Methodology

Reviewed the diff at `/tmp/qg-diff-1771469414.txt` against the ~1300-line existing `lib-interspect.sh` to assess:
1. Consistency with established conventions (naming, error handling, quoting, SQL escape patterns)
2. Shell idiom correctness (quoting, globbing, `set -e` interactions, heredoc safety)
3. Test suite robustness (accumulation vs abort, coverage gaps)
4. Documentation accuracy (pseudocode in command docs, cross-reference drift)

---

## Overall Assessment

**Verdict: needs-changes**

The overlay implementation is architecturally sound. It correctly applies the existing library's established patterns: `_interspect_flock_git` for serialisation, `_interspect_sql_escape` for all SQL values, `_interspect_sanitize` for content, `_interspect_validate_agent_name` for input validation, atomic temp-file-plus-mv for file writes, and awk state machines for frontmatter parsing. The path containment assertion (case-statement pattern) is a good security addition. Canary integration follows the same group_id compound-key pattern as existing routing overrides.

Two issues require fixes before this is production-safe:

1. **Q2 (MEDIUM):** Awk injection via unquoted shell variable in `_interspect_count_overlay_tokens` — the `word_count` value is interpolated directly into an awk program string, inconsistent with the rest of the library and exploitable if `wc` output is unexpected.

2. **Q7 (MEDIUM/LOW):** The test suite's `set -euo pipefail` at the top level aborts on the first unchecked non-zero exit, defeating the `FAIL` accumulator and producing misleading results — later tests never run when an earlier one fails.

The heredoc in `_interspect_write_overlay_locked` (Q1) is a style concern: if `${content}`, `${created_by}`, or `${evidence_ids}` ever contain the literal string `OVERLAY` on its own line, the heredoc terminates prematurely. This is low-probability given the upstream sanitization, but using printf with a temp file (as the commit message already does) would be strictly safer and consistent.

---

## Detailed Findings

### Q1. MEDIUM — Heredoc in `_interspect_write_overlay_locked` risks premature termination

**File:** `hub/clavain/hooks/lib-interspect.sh`
**Location:** `_interspect_write_overlay_locked`, around the `cat > "$tmpfile" <<OVERLAY` block

The overlay file body is written using an unquoted heredoc:
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

The variables `${content}`, `${created_by}`, and `${evidence_ids}` are expanded into the heredoc. If any of these contain the string `OVERLAY` on a line by itself (which the sanitizer does not explicitly block), the heredoc terminates early, leaving the file truncated and syntactically malformed. This is defended somewhat by upstream sanitization that removes control characters and injection patterns, but the sanitizer does not have a rule for `^OVERLAY$`. Elsewhere in the same function, the commit message is written via `printf` to a `mktemp` file specifically to avoid this class of issue.

**Fix:** Write the overlay file using `printf` to a temp file before the flock section, or quote the heredoc terminator (`<<'OVERLAY'`) and perform variable substitution via `sed`/`printf` afterward. The simplest safe approach:
```bash
{
    printf -- '---\nactive: true\ncreated: %s\ncreated_by: %s\nevidence_ids: %s\n---\n%s\n' \
        "$created" "$created_by" "$evidence_ids" "$content"
} > "$tmpfile"
```

### Q2. MEDIUM — Awk injection via `word_count` interpolation in `_interspect_count_overlay_tokens`

**File:** `hub/clavain/hooks/lib-interspect.sh`
**Location:** `_interspect_count_overlay_tokens`

```bash
word_count=$(printf '%s' "$content" | wc -w | tr -d ' ')
awk "BEGIN { printf \"%d\", ${word_count} * 1.3 }"
```

`word_count` is interpolated directly into the awk program string using a double-quoted `"..."`. `wc -w` normally produces a non-negative integer, but:
- On some locales, `wc` output includes extra whitespace that `tr -d ' '` may not fully clean.
- If the pipe fails in unusual ways, `word_count` could be empty or non-numeric, causing awk to receive `BEGIN { printf "%d",  * 1.3 }` — a syntax error.
- A non-numeric `word_count` could inject arbitrary awk code.

The established library pattern for passing shell variables to awk is `awk -v name="$val" '...'`. Fix:
```bash
awk -v wc="$word_count" 'BEGIN { printf "%d", wc * 1.3 }'
```

This is safe regardless of `word_count` content and consistent with awk usage throughout `lib-interspect.sh`.

### Q3. LOW — Test suite `set -euo pipefail` defeats the `FAIL` accumulator

**File:** `hub/clavain/test-interspect-overlay.sh`
**Location:** Line 8, and throughout

The test file opens with `set -euo pipefail`. The framework defines a `fail()` function that increments a counter and continues, intending to run all 42 tests and report aggregate results. However, `set -e` means any unchecked non-zero exit aborts the script — including function calls inside test blocks that aren't explicitly captured with `&& status=0 || status=$?`.

Most tests correctly wrap tested calls, but Test 12 contains:
```bash
if [[ $status -eq 0 ]]; then
    body=$(_interspect_overlay_body .clavain/interspect/overlays/fd-test/overlay-inject.md)
    if [[ "$body" == *"<system>"* ]]; then
```
If `_interspect_overlay_body` returns non-zero for any reason, `set -e` aborts the script at `body=$(...)`, all subsequent tests are skipped, `FAIL` is under-counted, and the exit code is 1 — indistinguishable from a proper test failure. The user sees "SOME TESTS FAILED" but cannot tell whether tests 13-19 passed.

**Fix:** Remove `set -e` from the test harness (keep `set -uo pipefail`). Add `|| true` at individual call sites where a non-zero exit is the expected signal. The `fail()` function already handles the "keep going" logic.

### Q4. LOW — `echo "$evidence_ids"` for jq validation uses `echo` instead of `printf '%s'`

**File:** `hub/clavain/hooks/lib-interspect.sh`
**Location:** `_interspect_write_overlay`, jq validation block

```bash
if ! echo "$evidence_ids" | jq -e 'type == "array"' >/dev/null 2>&1; then
```

The rest of the library uses `printf '%s'` for all string-to-pipe operations (seen in `_interspect_sanitize`, `_interspect_redact_secrets`, `_interspect_count_overlay_tokens`, `_interspect_insert_evidence`). `echo` with a value starting with `-n` or `-e` may be interpreted as a flag by some shells/environments. While `evidence_ids` is validated upstream, the inconsistency is a maintenance risk.

**Fix:**
```bash
if ! printf '%s\n' "$evidence_ids" | jq -e 'type == "array"' >/dev/null 2>&1; then
```

### Q5. LOW — `local` keyword in interspect-status.md pseudocode used outside a function context

**File:** `hub/clavain/commands/interspect-status.md`
**Location:** `Active Overlays` bash snippet

```bash
local escaped_agent
escaped_agent=$(_interspect_sql_escape "$agent")
```

This appears inside a fenced bash block in a command document, presented as executable pseudocode for agents to follow. `local` is only valid inside a bash function; using it at script scope is a bash error. This does not affect runtime since agents interpret command docs as instructions rather than executing them verbatim, but it sets a bad pattern if the pseudocode is ever extracted for testing.

**Fix:** Replace `local escaped_agent` with a plain `escaped_agent=` assignment, or add a comment `# (local — used in shell function context)`.

### Q6. INFO — `launch.md` inlines the awk state machine rather than referencing the helper function

**File:** `plugins/interflux/skills/flux-drive/phases/launch.md`
**Location:** Step 2.1d

The step inlines the full awk one-liner:
```
awk '/^---$/ { if (++delim == 2) exit } delim == 1 && /^active: true$/ { found=1 } END { exit !found }'
```
rather than referencing `_interspect_overlay_is_active` by name. If the implementation changes in `lib-interspect.sh`, the launch doc will drift and produce inconsistent results. The step should reference the function name and note it is implemented in `lib-interspect.sh`.

### Q7. INFO — Token budget ceiling (500) duplicated as literal across three files

The 500-token ceiling appears in:
- `lib-interspect.sh`: `(( total_tokens > 500 ))`
- `launch.md`: "exceeds 500 tokens"
- `interspect-propose.md`: "20-use window, 14-day expiry" (adjacent, same pattern)
- `interspect-status.md`: "token_est > 400: ⚠ near budget (500)"

The existing `confidence.json` schema already carries configurable thresholds for canary windows. An `overlay_token_budget` field (default 500) loaded via `_interspect_load_confidence` would unify the ceiling and make it adjustable for projects with larger agents. This matches the established extensibility pattern.

### Q8. INFO — Test 19 agent name negative coverage is shallow

**File:** `hub/clavain/test-interspect-overlay.sh`
**Location:** Test 19

Only one invalid agent name is tested ("INVALID"). The overlay ID validator (Test 8) covers 5 distinct negative cases: path traversal, uppercase, leading hyphen, empty. The agent name validator is equally important as a path component — adding cases for empty string `""`, path traversal `"../fd-escape"`, and shell metacharacter `"fd-test;rm -rf"` would bring parity.

---

## What Is Working Well

- **Awk frontmatter parsers** — `_interspect_overlay_is_active` and `_interspect_overlay_body` correctly use delimiter-counting state machines that are immune to `---` and `active: true` in body content. This is a non-trivial correctness requirement handled cleanly.
- **Naming consistency** — all new functions follow the `_interspect_` prefix convention. `_interspect_validate_overlay_id`, `_interspect_read_overlays`, `_interspect_write_overlay`, `_interspect_disable_overlay`, and their `_locked` variants all follow the established pattern.
- **Flock integration** — `_interspect_flock_git` is used correctly; budget check, file write, git commit, and DB inserts all happen inside a single flock acquisition. This is the TOCTOU-safe design the existing lib requires.
- **Path containment** — the `case "$fullpath" in "${overlays_root}"*)` assertion before `_interspect_validate_target` is a solid defense-in-depth layer even after ID validation.
- **Atomic file write** — temp-file-plus-mv pattern is used for both write and disable operations, consistent with the rest of the library.
- **Rollback on git failure** — both locked functions correctly remove/restore the file and unstage on git commit failure.
- **`_interspect_sanitize` extension** — the `max_chars` parameter addition is backward-compatible (default 500 preserves existing behavior) and clearly documented.
- **Sorted glob in `_interspect_read_overlays`** — `printf '%s\n' ... | sort` ensures deterministic overlay ordering, which is important for reproducible token budget calculations.
- **Test setup** — the test creates a full git repo with required fixtures (`protected-paths.json`, `confidence.json`) before sourcing the library, and uses `trap 'rm -rf "$TESTDIR"' EXIT` for cleanup.
