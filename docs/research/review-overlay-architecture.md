# Architecture Review: Interspect Overlay System (Type 1 Modifications)

**Reviewer:** fd-architecture (Flux-drive Architecture & Design Reviewer)
**Date:** 2026-02-18
**Diff:** `/tmp/qg-diff-1771469414.txt`
**Primary output:** `/root/projects/Interverse/.clavain/quality-gates/fd-architecture.md`

---

## Codebase Context

Operating in codebase-aware mode. Documentation read:

- `/root/projects/Interverse/plugins/interflux/CLAUDE.md` — interflux plugin conventions
- `/root/projects/Interverse/hub/clavain/CLAUDE.md` — Clavain conventions
- `/root/projects/Interverse/CLAUDE.md` — monorepo structure
- `hub/clavain/hooks/lib-interspect.sh` — full existing file (1700 lines after patch)
- `hub/clavain/test-interspect-overlay.sh` — 42-test integration suite
- `plugins/interflux/skills/flux-drive/phases/launch.md` — launch phase spec

---

## Change Summary

This diff adds the overlay subsystem (Type 1 modifications) to the existing interspect infrastructure. Key additions:

1. **`lib-interspect.sh` (+406 lines):** Seven new public shell functions — two YAML parsers (`_interspect_overlay_is_active`, `_interspect_overlay_body`), three read/count functions (`_interspect_read_overlays`, `_interspect_count_overlay_tokens`, `_interspect_validate_overlay_id`), one write function (`_interspect_write_overlay` + locked inner), one disable function (`_interspect_disable_overlay` + locked inner). Plus a two-line change to `_interspect_sanitize` to accept a `max_chars` parameter.

2. **Command specs (+3 files):** `interspect-propose.md` adds overlay proposal logic for the 40-79% `agent_wrong_pct` band. `interspect-revert.md` adds disambiguation between routing override and overlay revert. `interspect-status.md` adds an overlay table view.

3. **Launch spec (`launch.md`, interflux):** Adds Step 2.1d — overlay loading per agent before prompt construction. Adds `## Overlay Context` section to the agent prompt template.

---

## Boundaries & Coupling Analysis

### Layer map

The change touches the following layers and their interactions:

```
[interspect command specs] → [lib-interspect.sh] → [SQLite DB + git + filesystem]
[interflux launch.md spec] → [filesystem: .clavain/interspect/overlays/] → [agent prompts]
```

**Boundary integrity:** All overlay shell functions are correctly placed in `lib-interspect.sh` — the library is the single shell-level authority for interspect operations, consistent with how routing override helpers were previously added. No overlay logic appears in the evidence hooks (`interspect-evidence.sh`, `interspect-session.sh`). The command specs reference the library functions by name rather than re-implementing logic inline.

**Cross-repo dependency:** The overlay directory format (`.clavain/interspect/overlays/<agent>/<id>.md`) is defined in Clavain's library but consumed by interflux's `launch.md`. This is a pre-existing pattern — the routing overrides file (`.claude/routing-overrides.json`) follows the same cross-repo file dependency. The coupling is intentional and documented. No new coupling patterns are introduced.

**Data flow:** Evidence IDs collected in `interspect-propose.md` flow into `_interspect_write_overlay`, which writes them into both the overlay frontmatter and the `modifications` + `canary` DB tables. The DB records use a compound `group_id` of `{agent}/{overlay_id}` (matching the existing routing override pattern), which allows the disable path to find and update records without a secondary index on overlay_id.

**Scope assessment:** The change surface is proportional to the feature. The `_interspect_sanitize` parameter addition is a minimal, backward-compatible change (default preserves existing 500-char behavior). No unrelated modules are touched. The plugin.json and CLAUDE.md description updates are cosmetic housekeeping.

### Integration seam: launch.md overlay injection

The new Step 2.1d in `launch.md` sits between domain profile loading (2.1c) and temp file writing (also 2.1c — note the step number conflict, discussed in A2 below). The fallback contract is correct: missing directory or no active overlays silently skips the section. The budget truncation on the read side (500 tokens) mirrors the write-side enforcement in `_interspect_write_overlay_locked`. The injection point — as a separate `## Overlay Context` section below `## Domain Context` — is non-invasive and does not alter the existing section structure.

**Risk:** The re-sanitization in Step 2.1d is inline awk/string matching rather than a call to `_interspect_sanitize`. This is a divergence risk identified as finding A2.

---

## Pattern Analysis

### Alignment with existing patterns

**awk state machine parsers:** The new YAML parsers follow the identical delimiter-counting pattern used throughout the hooks library. `_interspect_overlay_is_active` and `_interspect_overlay_body` are clean and correct — the `delim == 1` guard before matching `active: true` is the right boundary condition to prevent body content from polluting frontmatter reads. Test 3 and Test 4 in the test suite explicitly cover these cases.

**flock serialization:** `_interspect_write_overlay` and `_interspect_disable_overlay` both use the existing `_interspect_flock_git` wrapper with the outer/inner function split pattern established by `_interspect_apply_routing_override`. The split correctly moves `set -e` to the inner function so early-exit failures propagate through the subshell boundary. This is consistent.

**Temp file + mv atomicity:** The `tmpfile="${fullpath}.tmp.$$"` pattern matches how `_interspect_write_routing_overrides` does atomic file writes (line 558). The rollback on git commit failure (`rm -f "$fullpath"` + `git reset HEAD`) mirrors the pattern in the routing override locked path.

**SQL escaping:** All user-controlled values that appear in SQL strings use `_interspect_sql_escape`. The `group_id` is constructed from two individually escaped components. This is correct.

**Validation layering:** The write path has three validation layers — pre-flock (agent name, overlay ID format, evidence_ids JSON type, path containment assertion, `_interspect_validate_target`), inside-flock (dedup file existence check, token budget), and sanitization (character stripping, secret redaction, injection-pattern rejection). This matches the existing routing override defense-in-depth approach.

**Naming:** All new functions use the `_interspect_` prefix and the `_overlay_` noun, consistent with `_interspect_apply_routing_override`, `_interspect_read_routing_overrides`, etc.

### Anti-patterns and deviations

**A1 — `_interspect_flock_git` API contract:** See findings. The function's comment says "git add / git commit" but both the routing override and overlay code use it to call shell functions. Works, but the comment is wrong.

**A2 — Inline parser duplication in `launch.md`:** The spec file copies the awk expression verbatim instead of referencing the library function. The library explicitly documents that the awk parsers are the single source of truth.

**A4 — Heredoc with variable expansion:** Unquoted heredoc delimiter in `_interspect_write_overlay_locked`. Lower risk due to upstream sanitization, but inconsistent with the commit message construction in the same function which uses `printf`.

**A6 — `local` outside function in status snippet:** Minor, does not affect runtime behavior of the spec.

### Duplication assessment

**Intentional duplication:** The `interspect-revert.md` overlay revert section duplicates the overlay-listing loop from `interspect-status.md`. This is appropriate — the revert flow needs interactive selection while status is read-only display. Consolidating into a helper would add indirection without benefit.

**Accidental duplication:** The double call to `_interspect_redact_secrets` in `_interspect_write_overlay` (A7). The awk parser inline in `launch.md` vs the library function (A2).

---

## Simplicity & YAGNI Analysis

**Abstraction quality:** The public/locked function split is necessary for the flock pattern to work and is well-established in this codebase. The seven new public functions each have a single, clear responsibility. No speculative extension points were added.

**Budget enforcement design:** The 500-token budget check is enforced at write time (inside flock, TOCTOU-safe) and re-checked at read time in `launch.md`. The write-side check uses combined existing+new content, correctly catching the case where a second overlay would push an agent over budget even if each individual overlay is under budget. This is the right design.

**Token estimation consistency:** The `wc -w * 1.3` formula is used in both `_interspect_count_overlay_tokens` and the `launch.md` budget check. The comment in `launch.md` explicitly flags that the implementations must match ("this MUST match the write-time implementation"). This is appropriate documentation for a cross-module invariant.

**Test coverage:** The 42-test suite covers all critical paths: active/inactive detection, body extraction with tricky content (embedded `active: true`, embedded `---` rules), token counting, concatenation, ID validation, full write lifecycle, dedup, budget rejection, prompt injection sanitization, path containment, DB records (compound group_id), disable lifecycle, disable idempotency, and invalid agent name rejection. This is thorough coverage for the attack surface.

**Required vs accidental complexity:**
- The flock + outer/inner function split is required complexity (concurrent agent sessions).
- The awk state machine is required complexity (safe YAML parsing without a YAML library in bash).
- The double `_interspect_redact_secrets` call (A7) is accidental complexity.
- The path containment `case` assertion in addition to `_interspect_validate_target` is arguably redundant (the validate_target function covers the allow-list), but is a cheap defense-in-depth check that pays for itself if `_interspect_validate_target`'s manifest is misconfigured.

---

## Verdict: needs-changes

Two findings require changes (A1, A2). A1 is a comment fix. A2 requires updating `launch.md` to reference the library function or add a sync-note. The remaining findings are low-priority cleanup.

**Safe to merge after:** A1 comment fix in `lib-interspect.sh` and A2 reference update in `launch.md`. All other findings can be addressed in a follow-up.

**Not required to block merge:** A3 (safe in practice, document only), A4 (safe in practice), A5 (benign race), A6 (spec pseudocode), A7 (idempotent, minor).
