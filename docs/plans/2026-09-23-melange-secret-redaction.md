# Melange artifact redaction

## Goal

Prevent a secret read during `/flux-melange` from entering a findings artifact. The observed failure was an npm `_authToken` copied from `~/.npmrc` into a probe adjudication Markdown file. The change covers npm auth values, common GitHub and API token forms, and PEM private keys. It leaves token rotation and other plugins outside this task.

## Design

1. Add one deterministic text scrubber and a `PreToolUse` hook for `Write` and `Edit` calls targeting `docs/research/flux-melange/`. The hook replaces secret-shaped values in the tool input before Claude Code executes the write. It preserves all other tool fields and fails closed if it cannot process a matching write.
2. Deny Bash commands referencing the melange output tree, except simple directory creation and the shared findings helper. That helper scrubs melange JSONL lines in memory before appending. Require `Write` or `Edit` for other findings, ledger, verifier, adjudicator and synthesis artifacts in both workflow and prose paths.
3. Reject peer mirrors before dispatch. Their external CLIs write directly to disk, bypassing Claude's hook; preserving peer mode requires a separate before-disk write boundary.

## Test and acceptance

- First add a regression that creates a fake home `.npmrc` with `_authToken`, constructs a probe finding from it, feeds the finding to the hook, applies the returned `Write` input, and checks the on-disk file has a redaction marker and not the fake value. It failed before the hook was added.
- Add focused cases for `Edit`, GitHub/API tokens, PEM keys, and nonsecret text. Confirm valid JSON findings remain parseable after scrubbing.
- Run `uv run pytest tests/ -q` and `bash tests/test-findings-flow.sh`. Inspect the final diff and scan changed fixtures for accidental real secrets. A live Claude Code canary using a fake npm token must confirm `updatedInput` is honored by the installed hook. A full melange run is optional because it invokes many paid model calls.

## Risks and escalation

The hook only intercepts Claude file tools and Bash commands whose target path is visible in the command or current directory. The prompt contract and helper cover the expected write paths; a dynamically constructed Bash path remains a limit of command inspection. Mirror CLI runs fail closed. The workflow journal may retain structured return values outside the findings tree; journal retention is outside this artifact fix. Preserve current model routing and output schemas.

## Verification state (2026-09-23)

- `uv run pytest tests/ -q`: 433 passed, 2 skipped. `bash tests/test-findings-flow.sh`: 16 passed. Focused tests also cover unquoted numeric token fields without breaking JSONL and repeated slashes in shell target paths.
- Live Claude Code canaries: a main-session Write placed `[REDACTED SECRET]` on disk, and a Bash write to the same output tree was denied before creating a file.
- The independent Fable review confirmed the original leak paths were closed, then requested a Workflow-spawned agent canary. That canary did not start: BB Account Pooler returned 429 with no eligible Claude account. Do not merge or claim full Workflow coverage until this check runs after quota resets.
