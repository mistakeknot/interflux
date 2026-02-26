# Bump and Publish: interpath v0.2.3

**Date:** 2026-02-23
**Plugin:** interpath
**Previous version:** 0.2.2
**New version:** 0.2.3

## Summary

Bumped interpath from v0.2.2 to v0.2.3 using the `interbump.sh` script located at `/home/mk/projects/Demarch/scripts/interbump.sh`.

## Steps Executed

1. **Version check** — Confirmed current version was 0.2.2 via marketplace.json query.
2. **interbump.sh** — Ran from within `/home/mk/projects/Demarch/interverse/interpath`. The script automatically:
   - Updated `.claude-plugin/plugin.json` (interpath repo)
   - Updated `../../core/marketplace/.claude-plugin/marketplace.json` (marketplace repo)
   - Ran pre-publish validation (plugin.json valid, all declared files exist, 0 errors/0 warnings)
   - Committed and pushed interpath (`chore: bump version to 0.2.3`, commit `d0b00a1`)
   - Committed and pushed marketplace (`chore: bump interpath to v0.2.3`, commit `4eb9596`)
   - Installed interbase.sh v1.0.0 to `/home/mk/.intermod/interbase/`
3. **Verification** — Confirmed both `plugin.json` and `marketplace.json` now report version 0.2.3.

## Key Findings

- **interbump.sh handles the full workflow**: version bump, validation, commit, push for both plugin and marketplace repos. No manual steps needed.
- **Commit messages are baked into the script**: The script generates its own commit messages (`chore: bump version to X.Y.Z` for the plugin, `chore: bump <name> to vX.Y.Z` for the marketplace). Co-Authored-By trailers are not included by the script's own commit logic.
- **Pre-publish validation is automatic**: The script runs `validate-plugin` before applying changes, catching structural issues early.

## Files Changed

| Repository | File | Change |
|---|---|---|
| interpath | `.claude-plugin/plugin.json` | `"version": "0.2.2"` -> `"version": "0.2.3"` |
| marketplace | `.claude-plugin/marketplace.json` | interpath entry version `0.2.2` -> `0.2.3` |

## Post-Publish Note

Restart Claude Code sessions to pick up the new plugin version.
