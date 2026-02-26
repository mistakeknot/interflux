# Bump and Publish: interserve v0.1.5

**Date:** 2026-02-23
**Plugin:** interserve
**Previous version:** 0.1.4
**New version:** 0.1.5

## Analysis

### Pre-bump State
- interserve was at version 0.1.4 in both the plugin repo and the marketplace.
- The plugin repo (`/home/mk/projects/Demarch/interverse/interserve`) was clean with no uncommitted changes.
- The marketplace (`/home/mk/projects/Demarch/core/marketplace`) tracked interserve at 0.1.4.

### Bump Process
Used the `interbump.sh` script located at `/home/mk/projects/Demarch/scripts/interbump.sh`. This script automates the full publish workflow:

1. **Version detection:** Reads current version from `.claude-plugin/plugin.json` (0.1.4)
2. **Pre-publish validation:** Runs `validate-plugin` — passed with 0 errors, 1 warning (hooks.json on disk but not declared in plugin.json, auto-loaded)
3. **Plugin repo update:** Updated `.claude-plugin/plugin.json` version field to 0.1.5
4. **Plugin commit + push:** Committed and pushed to `mistakeknot/interserve` on main
5. **Marketplace update:** Updated `marketplace.json` entry for interserve to 0.1.5
6. **Marketplace commit + push:** Committed and pushed to `mistakeknot/interagency-marketplace` on main
7. **Cache bridging:** Symlinked cache/0.1.5 to 0.1.4 for running sessions
8. **Interbase install:** Installed interbase.sh v1.0.0 to `/home/mk/.intermod/interbase/`

### Post-bump Amendments
The interbump script does not include `Co-Authored-By` trailers. Both commits were amended to add the required co-author line and pushed:

- **interserve repo:** `c9e1020` — `chore: bump version to 0.1.5`
- **marketplace repo:** `90648e4` — `chore: bump interserve to v0.1.5`

### Validation Warning
```
[WARN]  hooks/hooks.json exists on disk but not declared in plugin.json (may be auto-loaded)
```
This is a known pattern — hooks.json is auto-discovered by Claude Code and does not need explicit declaration in plugin.json. Not a blocking issue.

## Files Modified

### interserve repo (`/home/mk/projects/Demarch/interverse/interserve`)
- `.claude-plugin/plugin.json` — version field: `0.1.4` → `0.1.5`

### marketplace repo (`/home/mk/projects/Demarch/core/marketplace`)
- `.claude-plugin/marketplace.json` — interserve version: `0.1.4` → `0.1.5`

## Result
interserve v0.1.5 is published and available in the marketplace. Restart Claude Code sessions to pick up the new version.
