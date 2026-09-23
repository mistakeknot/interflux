# Melange artifact redaction

## Goal

Prevent a secret read during `/flux-melange` from entering a findings artifact. The observed failure was an npm `_authToken` copied from `~/.npmrc` into a probe adjudication Markdown file. The change covers npm auth values, common GitHub and API token forms, and PEM private keys. It leaves token rotation and other plugins outside this task.

## Design

1. Add one deterministic text scrubber and a `PreToolUse` hook for `Write` and `Edit` calls targeting `docs/research/flux-melange/`. The hook replaces secret-shaped values in the tool input before Claude Code executes the write. It preserves all other tool fields and fails closed if it cannot process a matching write.
2. Deny Bash commands referencing the melange output tree, except simple directory creation and the shared findings helper. That helper scrubs melange JSONL lines in memory before appending. Require `Write` or `Edit` for other findings, ledger, verifier, adjudicator and synthesis artifacts in the prose path.
3. Reject peer mirrors before dispatch. Their external CLIs write directly to disk, bypassing Claude's hook; preserving peer mode requires a separate before-disk write boundary.
4. Run the prose path for every invocation. A live Workflow probe wrote a fake npm token unchanged: its `agent()` subagent did not run the plugin's `PreToolUse` hook. A live ordinary `Agent` subagent did run that hook and wrote only the redaction marker. The Workflow entry point therefore throws before dispatch, including for direct calls, until it has a guarded write boundary.
5. Dispatch seed and later prose probes directly as `interflux:melange-worker`, whose tools are limited to Read, Grep, Glob, Write, and Edit. This prevents the nested flux-engine external dispatch lane from writing findings without the hook. The same restricted worker handles melange design, assay, verification, and synthesis subagents. The orchestrator creates directories with `mkdir -p`; workers write artifacts with guarded file tools. Lens specs live under the guarded melange output tree, and a narrow Bash exception lets the orchestrator run only the known generator against those scrubbed specs.

## Test and acceptance

- First add a regression that creates a fake home `.npmrc` with `_authToken`, constructs a probe finding from it, feeds the finding to the hook, applies the returned `Write` input, and checks the on-disk file has a redaction marker and not the fake value. It failed before the hook was added.
- Add focused cases for `Edit`, GitHub/API tokens, PEM keys, and nonsecret text. Confirm valid JSON findings remain parseable after scrubbing.
- Run `uv run pytest tests/ -q` and `bash tests/test-findings-flow.sh`. Inspect the final diff and scan changed fixtures for accidental real secrets. A live Claude Code ordinary `Agent` canary using a fake npm token must confirm `updatedInput` is honored before disk. The Workflow entry point must fail before calling any agent. A full melange run is optional because it invokes many paid model calls.

## Risks and escalation

The hook only intercepts Claude file tools and Bash commands whose target path is visible in the command or current directory. The prompt contract and helper cover the expected write paths; a dynamically constructed Bash path remains a limit of command inspection. Mirror CLI and Workflow runs fail closed. Prior Workflow journals may retain structured return values outside the findings tree; journal retention is outside this artifact fix. Preserve current model routing and output schemas in the active prose path.

## Verification state (2026-09-23)

- `uv run pytest tests/ -q`: 435 passed, 2 skipped. `bash tests/test-findings-flow.sh`: 16 passed. Focused tests also cover unquoted numeric token fields without breaking JSONL and repeated slashes in shell target paths.
- Live Claude Code canaries: a main-session Write placed `[REDACTED SECRET]` on disk, and a Bash write to the same output tree was denied before creating a file.
- After pool capacity returned, the Workflow-spawned canary wrote the fake token unchanged. The ordinary `Agent` subagent canary wrote `[REDACTED SECRET]` and the debug log showed `PreToolUse:Write` modified its input. Workflow dispatch is now disabled and its entry point fails closed.
- Independent review found that a prose probe could invoke flux-engine's external dispatch lane and that flux-engine's shell-based launch sequence would conflict with the melange guard. Probes now dispatch directly through the restricted worker. A live restricted-worker canary wrote the redaction marker instead of the fake token; a second canary confirmed it had no Bash tool even when the parent allowed Bash.
- Follow-up review found the same nested dispatch pattern in the seed round. Seed reviews now use the restricted worker directly; design specs are written inside the guarded output tree before the orchestrator runs the lens generator.
- Final independent review found no concrete blockers after the seed change. It confirmed the generator allowlist and the guarded paths for seed, probe, adjudication, assay, verification, and synthesis.
