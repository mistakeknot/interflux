---
lastConfirmed: 2026-03-07
provenance: compound
---
Executor agents need explicit autonomous decision boundaries. Without them, executors either over-fix (touching unrelated code) or under-fix (stopping for trivial blockers). Four rules provide the right granularity:

- R1 Auto-fix bugs (wrong queries, type errors, null pointers) — no permission needed
- R2 Auto-add critical functionality (missing validation, auth, error handling) — no permission needed
- R3 Auto-fix blockers (missing deps, broken imports) — no permission needed
- R4 Ask about architectural changes (new DB tables, framework switches, breaking APIs) — user decision required

Priority chain: R4 (stop) > R1-R3 (auto-fix) > unsure (treat as R4).

Scope boundary: only fix issues DIRECTLY caused by the current task. Pre-existing issues go to deferred-items, not inline fixes. Fix attempt limit: 3 per task, then defer.

Analysis paralysis guard: 5+ consecutive reads without writes = stuck signal. Forces either writing code or declaring blocked.

Evidence: GSD executor agent (research/get-shit-done/agents/gsd-executor.md) validated these rules across multi-phase plan execution. Adapted for Clavain in os/clavain/skills/executing-plans/SKILL.md.
Verify: Check that executing-plans SKILL.md contains a "Deviation Rules" section with Rules 1-4.
