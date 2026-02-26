# Bump and Publish: interwatch

**Date:** 2026-02-23
**Previous version:** 0.1.3 (marketplace) / 0.1.4 (plugin.json — never published)
**New version:** 0.1.5

## Analysis

### Pre-Bump State

The interwatch plugin had a version mismatch before this operation:

- **plugin.json** showed `0.1.4` — this version was set at some point but never formally published via interbump
- **marketplace.json** showed `0.1.3` — the last version that was properly published
- The last formal version bump commit was `c4f98a5` ("chore: bump version to 0.1.2")
- The 0.1.4 version in plugin.json was likely set manually during some update but the marketplace was never synced

### Version Files

Only one version file exists in the interwatch plugin:

| File | Type | Pre-bump | Post-bump |
|------|------|----------|-----------|
| `.claude-plugin/plugin.json` | JSON | 0.1.4 | 0.1.5 |
| `skills/doc-watch/SKILL.md` | Markdown | (no version field) | N/A |

### Interbump Execution

The `interbump.sh` script was used (located at `/home/mk/projects/Demarch/scripts/interbump.sh`).

**Dry-run result:** Failed verification check in dry-run mode (expected 0.1.5 but file still showed 0.1.4 since dry-run doesn't write). This is a known limitation of the dry-run verify step.

**Live run result:** Successful. The script:
1. Ran `validate-plugin` — 0 errors, 1 warning (version mismatch between plugin.json and marketplace.json, which was expected)
2. Updated `.claude-plugin/plugin.json` from 0.1.4 to 0.1.5
3. Updated marketplace.json from 0.1.3 to 0.1.5
4. Committed and pushed the plugin repo (`interwatch`)
5. Committed and pushed the marketplace repo (`interagency-marketplace`)
6. Installed `interbase.sh v1.0.0` to `~/.intermod/interbase/`

### Post-Bump Amendments

The interbump script does not include `Co-Authored-By` trailers in its commit messages. Both commits were amended with:

```
Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

And force-pushed with `--force-with-lease` (safe since the commits were just pushed moments earlier by the same session).

### Final Commit SHAs

| Repo | SHA | Message |
|------|-----|---------|
| interwatch | `9650ba0` | chore: bump version to 0.1.5 |
| interagency-marketplace | `423d638` | chore: bump interwatch to v0.1.5 |

### Verification

Post-bump verification confirmed both locations read `0.1.5`:
- `interwatch/.claude-plugin/plugin.json` → 0.1.5
- `marketplace/.claude-plugin/marketplace.json` (interwatch entry) → 0.1.5

## Key Findings

1. **Version drift detected:** The plugin had 0.1.4 in plugin.json but 0.1.3 in marketplace — indicating a previous version change was not published through interbump. Always use interbump for version changes to keep both in sync.

2. **Interbump short-circuits on matching version:** Running `interbump.sh 0.1.4` when plugin.json already showed 0.1.4 resulted in "already at 0.1.4 — nothing to do", even though marketplace was at 0.1.3. This means interbump cannot be used to retroactively sync marketplace for a version already in plugin.json — you must bump to a new version.

3. **Interbump dry-run verify limitation:** The `--dry-run` flag shows what files would be updated but the verification step fails because no files are actually written. This is a cosmetic issue (exit code 1) but can be confusing.

4. **Interbump handles full lifecycle:** The script auto-discovers the marketplace path, validates the plugin, updates all version files, commits, pulls with rebase, and pushes both the plugin and marketplace repos. It also installs interbase.sh. No manual steps needed beyond running the script.
