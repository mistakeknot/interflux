# Bump and Publish: interflux v0.2.24

**Date:** 2026-02-23
**Plugin:** interflux
**Previous version:** 0.2.23
**New version:** 0.2.24

## Analysis

### Pre-bump State
- interflux was at version 0.2.23 in both the plugin repo and the marketplace.
- The plugin repo (`/home/mk/projects/Demarch/interverse/interflux`) had one untracked modification (`.clavain/interspect/interspect.db`) but was otherwise clean on main.
- The marketplace (`/home/mk/projects/Demarch/core/marketplace`) tracked interflux at 0.2.23.

### Validation Failures (Fixed Before Bump)
The initial interbump attempt failed pre-publish validation with 2 errors:

1. **`agentCapabilities` unrecognized key:** The `plugin.json` contained an `agentCapabilities` field mapping agent files to capability tags. Claude Code rejects unrecognized keys, so this field was removed.
2. **Redundant `hooks` declaration:** The `plugin.json` declared `"hooks": "./hooks/hooks.json"` explicitly. Claude Code auto-loads `hooks/hooks.json` from the plugin root, so declaring it causes a duplicate hooks error. The `hooks` field was removed.

Both issues were fixed by running:
```bash
jq 'del(.agentCapabilities, .hooks)' .claude-plugin/plugin.json > /tmp/plugin-fixed.json && mv /tmp/plugin-fixed.json .claude-plugin/plugin.json
```

### Bump Process
Used the `interbump.sh` script at `/home/mk/projects/Demarch/scripts/interbump.sh`. On the second run (after fixes), the script completed successfully:

1. **Version detection:** Read current version from `.claude-plugin/plugin.json` (0.2.23)
2. **Pre-publish validation:** Passed with 0 errors, 1 warning (hooks.json on disk but not declared — expected, since we just removed the explicit declaration)
3. **Plugin repo update:** Updated `.claude-plugin/plugin.json` and `docs/PRD.md` version fields to 0.2.24
4. **Plugin commit + push:** Committed as `f42dcb6` and pushed to `mistakeknot/interflux` on main
5. **Marketplace update:** Updated `marketplace.json` entry for interflux to 0.2.24
6. **Marketplace commit + push:** Committed as `4894e5b`, but this commit was subsequently superseded — the interflux marketplace change was absorbed into commit `90648e4` (interserve bump) which included the staged interflux version change
7. **Cache bridging:** Symlinked cache/0.2.23 and cache/0.2.24 to 0.2.20 for running sessions
8. **Interbase install:** Installed interbase.sh v1.0.0 to `/home/mk/.intermod/interbase/`

### Co-Authored-By Note
The interbump script does not include `Co-Authored-By` trailers in its commits. The interflux repo commit (`f42dcb6`) was already pushed without the trailer. The marketplace change was committed and pushed as part of the interserve bump (`90648e4`), which does include the co-author trailer.

### Validation Warning (Non-blocking)
```
[WARN]  hooks/hooks.json exists on disk but not declared in plugin.json (may be auto-loaded)
```
This is the expected state after removing the redundant `hooks` declaration. Claude Code auto-discovers `hooks/hooks.json`, so no explicit declaration is needed.

## Files Modified

### interflux repo (`/home/mk/projects/Demarch/interverse/interflux`)
- `.claude-plugin/plugin.json` — version: `0.2.23` → `0.2.24`, removed `agentCapabilities` key, removed `hooks` key
- `docs/PRD.md` — version field: `0.2.23` → `0.2.24`

### marketplace repo (`/home/mk/projects/Demarch/core/marketplace`)
- `.claude-plugin/marketplace.json` — interflux version: `0.2.23` → `0.2.24`

## Result
interflux v0.2.24 is published and available in the marketplace. Restart Claude Code sessions to pick up the new version.
