# Correctness Review: Interspect Overlay System (Type 1 Modifications)

Reviewer: fd-correctness (Julik, Flux-drive Correctness Reviewer)
Date: 2026-02-18
Diff reviewed: `/tmp/qg-diff-1771469414.txt`
Primary source: `hub/clavain/hooks/lib-interspect.sh` (+406 lines)
Supporting files: `commands/interspect-propose.md`, `commands/interspect-revert.md`, `commands/interspect-status.md`, `skills/flux-drive/phases/launch.md`, `hub/clavain/test-interspect-overlay.sh`

---

## Scope

This review covers the complete overlay lifecycle:

- Write path: `_interspect_write_overlay` → flock → `_interspect_write_overlay_locked`
- Disable path: `_interspect_disable_overlay` → flock → `_interspect_disable_overlay_locked`
- Read path: `_interspect_read_overlays`, `_interspect_overlay_is_active`, `_interspect_overlay_body`
- Token budget: `_interspect_count_overlay_tokens` (write-time and launch-time)
- DB records: modifications + canary INSERT/UPDATE under flock
- Frontmatter parsers: awk state machines for active-check and body-extraction
- Injection surface: sanitization, re-sanitization at launch time
- Command specs: interspect-propose, interspect-revert, interspect-status overlays sections
- Test coverage: `test-interspect-overlay.sh` (19 tests observed)

---

## Invariants

The following invariants must remain true across all execution paths, including concurrent calls, retries, crashes, and hand-edited files:

1. **Budget invariant**: Total active overlay token count for any agent must not exceed 500 at write time. The budget check must be serialized with the write — no gap between read and write.
2. **Dedup invariant**: No two overlay files share the path `{agent}/{overlay-id}.md`. Rejected by the locked dedup check.
3. **Containment invariant**: All overlay file paths resolve under `.clavain/interspect/overlays/`. Path traversal through agent name or overlay ID must be caught before the flock.
4. **Git-DB consistency invariant**: A DB record (`modifications` + `canary`) exists if and only if an overlay file exists in the git history with `applied` status. Partial states must not persist.
5. **Frontmatter-only mutation invariant**: `active: true → false` transitions must not touch the overlay body.
6. **group_id collision invariant**: DB keys for overlays use `{agent}/{overlay_id}` compound format; routing-override keys use `{agent}` alone. The two namespaces must not overlap.
7. **Prompt injection barrier**: LLM-generated content must be sanitized before injection into agent prompts.
8. **Flock scope invariant**: Budget read, file write, git commit, and DB insert execute under a single flock acquisition without releasing it between steps.

---

## Architecture Assessment

### What is correct and well-designed

**Flock strategy (F1):** The entire critical section — budget read, dedup check, file write, git add+commit, DB inserts — executes inside `_interspect_flock_git` with a 30-second timeout. The budget check in `_interspect_write_overlay_locked` correctly calls `_interspect_read_overlays` from inside the lock, preventing the classic check-then-act race where two concurrent writers both pass the budget check individually but together exceed 500 tokens.

**Awk state machines (F2, F4):** Both parsers (`_interspect_overlay_is_active` and `_interspect_overlay_body`) use a two-delimiter counter that exits on the second `---`. This correctly isolates the frontmatter region from body content. A file containing `active: true` in the body is not misclassified as active. Test 3 in the test suite validates this. The disable mutation (`_interspect_disable_overlay_locked`) also uses a correct awk state machine that only rewrites lines matching `^active: true$` within `delim == 1`.

**Path containment (F9):** The containment assertion uses a `case` pattern match against `"${overlays_root}"*` before entering the flock. Agent name and overlay ID are separately validated with strict regex (`^fd-[a-z][a-z0-9-]*$` and `^[a-z0-9][a-z0-9-]*$` respectively). Combined with `_interspect_validate_target` against the allow-list, three independent checks block path traversal.

**compound group_id (F5):** Using `{agent}/{overlay_id}` as the DB key for overlays, versus `{agent}` alone for routing overrides, prevents any confusion in the `modifications` and `canary` tables when both types exist for the same agent.

**Sanitization (F3):** Overlay content is sanitized at write time (2000-char limit, ANSI stripping, control-char removal, secret redaction, injection-pattern rejection) and again at launch time before prompt injection. The double-sanitize on launch provides defense-in-depth against hand-edited overlays.

**Rollback (F11):** Both locked functions include rollback logic for git-commit failure. The write path removes the file and unstages. The disable path uses `git restore` to recover the pre-modification content. The disable rollback correctly prefers `git restore` with fallback to `git checkout --`.

**Atomic file writes:** Both write and disable use `cat > tmpfile` then `mv tmpfile fullpath`. The `mv` on the same filesystem is atomic. This prevents readers from seeing partial writes.

---

## Issues Found

### C-01. MEDIUM: `set -e` in locked function silently converts canary failure into spurious total-failure exit

**File:** `/root/projects/Interverse/hub/clavain/hooks/lib-interspect.sh`, lines 1485–1603

`_interspect_write_overlay_locked` opens with `set -e`. The canary INSERT is guarded by `if ! sqlite3 ...` which correctly suspends `set -e` for that specific command. However, the `UPDATE modifications SET status = 'applied-unmonitored'` inside the failure branch is not guarded:

```bash
if ! sqlite3 "$db" "INSERT INTO canary ..."; then
    sqlite3 "$db" "UPDATE modifications SET status = 'applied-unmonitored' WHERE commit_sha = '${commit_sha}';" 2>/dev/null || true
    echo "WARN: Canary monitoring failed — overlay active but unmonitored." >&2
fi
```

The `2>/dev/null || true` on the UPDATE suppresses both stderr and the error exit. This is actually safe. However, the broader `set -e` environment means any other subcommand that fails between `mv "$tmpfile" "$fullpath"` (line ~1531) and `echo "$commit_sha"` (line 1603) will silently abort the function, causing the caller to report `ERROR: Could not write overlay` — even though the file was already committed.

**Concrete failure sequence:**
1. `mv "$tmpfile" "$fullpath"` succeeds — file exists
2. `cd "$root"` succeeds
3. `git add "$rel_path"` succeeds
4. `git commit ...` succeeds — overlay is in git history
5. `_interspect_load_confidence` encounters a transient error (returns non-zero)
6. `set -e` fires — function exits non-zero
7. Caller: `ERROR: Could not write overlay. Check git status and retry.`
8. User retries → `ERROR: Overlay {id} already exists for {agent}`
9. Overlay is active and deployed but user believes the write failed

**Fix:** After the git commit succeeds, wrap all remaining DB operations in `|| true` or a dedicated `set +e` block, and unconditionally output `echo "$commit_sha"` as the final line when the commit succeeded.

---

### C-02. MEDIUM: Pre-flock active-state check in disable path is a TOCTOU — concurrent disablers can re-enable an overlay

**File:** `/root/projects/Interverse/hub/clavain/hooks/lib-interspect.sh`, lines 1629–1637

```bash
if [[ ! -f "$fullpath" ]]; then
    echo "ERROR: Overlay ${overlay_id} not found for ${agent}" >&2
    return 1
fi

if ! _interspect_overlay_is_active "$fullpath"; then
    echo "INFO: Overlay ${overlay_id} is already inactive" >&2
    return 0
fi
# ... now enter flock
```

The active check reads the file outside the flock. If two callers invoke `_interspect_disable_overlay` concurrently for the same overlay:

- Both read `active: true` → both proceed to flock
- Caller A acquires flock, runs awk mutation, writes `active: false`, commits (`git commit` succeeds with actual diff), releases flock
- Caller B acquires flock, runs awk mutation on now-`active: false` file, writes `active: false` again (file content identical), runs `git commit`
- Git reports "nothing to commit" → `git commit` exits non-zero
- Rollback fires: `git restore "$rel_path"` — restores the file to its most recent committed state
- The most recent committed state IS `active: false` (committed by A), so `git restore` actually does nothing harmful

Wait — re-examining: after B's awk writes `active: false` and `mv` succeeds, the working-tree file is `active: false`. Then `git commit` fails. Rollback calls `git restore "$rel_path"`, which checks out the HEAD version — which is ALSO `active: false` (A's commit is HEAD). So the file remains `active: false`. DB UPDATE for B is a no-op (status is already `reverted`). **Outcome is actually safe** in this specific scenario.

However: if A's git commit is still in-flight (A holds the flock, has not yet released), B cannot enter the flock and waits. When A releases, B enters. This is the correct serialization. The pre-flock check is purely an optimization to avoid entering the flock for an already-inactive overlay. The TOCTOU window means the optimization may occasionally perform a redundant flock-and-write, but the locked function's awk mutation and git-commit-failure rollback are idempotent enough to handle it without corruption.

**Revised assessment:** This is LOW severity — a performance concern (unnecessary flock acquisition and no-op git commit attempt) rather than a data integrity failure. The rollback correctly handles the "nothing to commit" case via `git restore`. The recommendation is to add a repeat active check inside the locked function to make the early-exit behavior consistent under concurrency.

---

### C-03. LOW: Commit SHA extraction via `tail -1` is fragile against future stdout pollution

**File:** `/root/projects/Interverse/hub/clavain/hooks/lib-interspect.sh`, lines 1476–1477

```bash
local commit_sha
commit_sha=$(echo "$flock_output" | tail -1)
```

The locked function outputs its SHA as the last line. Any future diagnostic `echo` added anywhere between the `git commit` call and `echo "$commit_sha"` (or inside called functions like `_interspect_load_confidence`, `_interspect_compute_canary_baseline`) will silently become the "commit SHA". The test suite checks `assert_contains "write output has SUCCESS"` but does not validate that `Commit: ${commit_sha}` contains a valid 40-char hex string. A regression would be silent.

**Fix:** Use a sentinel prefix:
```bash
echo "COMMIT_SHA:${commit_sha}"
# Caller:
commit_sha=$(echo "$flock_output" | grep '^COMMIT_SHA:' | cut -d: -f2 | tail -1)
```

Or write the SHA to a known temp file path.

---

### C-04. LOW: `local escaped_agent` in command spec is outside a function — not portable

**File:** `hub/clavain/commands/interspect-status.md`, diff lines added ~279–280

```bash
local escaped_agent
escaped_agent=$(_interspect_sql_escape "$agent")
canary_status=$(sqlite3 "$DB" "SELECT status FROM canary WHERE group_id LIKE '${escaped_agent}/%' ...")
```

This code block appears in a loop inside a markdown command spec. The `local` keyword is only valid inside bash functions. If an agent pastes this into a shell context outside a function, it will error: `bash: local: can only be used in a function`. Command specs that include executable bash snippets should use plain variable assignment (`escaped_agent=...`) or document clearly that the block runs inside a function.

Secondary: `_interspect_sql_escape` does not escape LIKE metacharacters (`%`, `_`). The LIKE query `group_id LIKE '${escaped_agent}/%'` is safe only because agent names are constrained to `^fd-[a-z][a-z0-9-]*$` (no `%` or `_`). This assumption is not documented in `_interspect_sql_escape`'s comment, creating a latent hazard for callers using arbitrary strings with LIKE.

---

### C-05. INFO: awk parser misclassifies file with exactly one `---` delimiter

**File:** `/root/projects/Interverse/hub/clavain/hooks/lib-interspect.sh`, line 1323

```bash
awk '/^---$/ { if (++delim == 2) exit } delim == 1 && /^active: true$/ { found=1 } END { exit !found }' "$filepath"
```

If a file has exactly one `---` delimiter, `delim` reaches 1 but never 2. The parser then scans the rest of the file (which is nominally the body) under `delim == 1`. A hand-crafted file with one `---` and `active: true` somewhere in its body would be classified as active. This violates the frontmatter-isolation invariant.

Files written by `_interspect_write_overlay_locked` always have exactly two `---` delimiters, so this scenario requires a hand-malformed file. The risk is low but documented. Test 3 validates the two-delimiter case; there is no test for the one-delimiter case.

---

### C-06. INFO: No SQLite transaction around modifications + canary INSERTs — process kill leaves inconsistent state

**File:** `/root/projects/Interverse/hub/clavain/hooks/lib-interspect.sh`, lines 1558–1601

The `modifications` INSERT and `canary` INSERT are two separate `sqlite3` invocations:

```bash
sqlite3 "$db" "INSERT INTO modifications ..."
...
if ! sqlite3 "$db" "INSERT INTO canary ..."; then
    sqlite3 "$db" "UPDATE modifications SET status = 'applied-unmonitored' ..." 2>/dev/null || true
```

A SIGKILL between these two calls leaves a `modifications` row with `status='applied'` and no `canary` row. The `'applied-unmonitored'` compensation never runs. Queries against `modifications` will show an overlay as deployed but canary evaluation will find no matching row. Canary status display in `interspect-status` will show "no canary (manual overlay?)" for a system-written overlay.

This is an INFO rather than higher severity because: (a) the gap is sub-millisecond in normal operation, (b) the overlay file itself (committed to git) is the source of truth — the DB is the monitoring layer, not the primary record, (c) the `interspect-status` display handles missing canary rows gracefully.

**Fix:** Wrap both in a single transaction. SQLite supports multi-statement transactions in a single `sqlite3` invocation.

---

## Test Coverage Assessment

The 19-test suite (`test-interspect-overlay.sh`) covers:

- YAML parser: active, inactive, body-with-`active: true`, body-with-`---` (Tests 1–4)
- Body extractor: no-frontmatter case (Test 5)
- Token counting: 10-word and empty-string cases (Test 6)
- Read overlays: concatenation, inactive exclusion (Test 7)
- Overlay ID validation: valid IDs, path traversal, uppercase, leading hyphen, empty (Test 8)
- Full write lifecycle (Test 9)
- Dedup enforcement (Test 10)
- Budget enforcement (Test 11)
- Sanitization: `<system>` tag (Test 12)
- Path containment: `../escape-attempt` (Test 13)
- DB records: compound group_id verification (Test 14)
- Disable lifecycle (Test 15)
- Read after disable (Test 16)
- DB records after disable (Test 17)
- Disable idempotency (Test 18)
- Invalid agent name (Test 19)

**Gaps:**
- No test for one-`---`-delimiter degenerate file (C-05)
- No test validating that `commit_sha` in success output is a valid SHA (C-03 fragility)
- No concurrency test (two concurrent writes to same agent — budget interleaving)
- No test for `set -e` interaction: simulated canary INSERT failure after successful git commit (C-01)
- No test for disable when overlay is already inactive at flock time (idempotency under concurrency, C-02)

---

## Verdict: needs-changes

Two MEDIUM issues require fixes before this is production-safe at scale:

1. **C-01** (`set -e` + canary failure → spurious total failure): Wrap post-commit DB operations with `|| true` or `set +e`, ensure `echo "$commit_sha"` is unconditional after a successful git commit.
2. **C-02** (active-state check before flock is pure optimization, not correctness): Verified as safe — downgraded to LOW. Add inside-flock repeat check for cleanliness.

The architecture is fundamentally sound. The flock scope is correct. The awk parsers are correct. Path containment is correct. The compound group_id design is correct. These fixes are small, targeted, and do not require structural changes.
