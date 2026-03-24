#!/usr/bin/env bash
# PostToolUse hook: warn when flux-drive skill files change but compact wasn't updated
# Fires on Edit/Write to skills/flux-drive/SKILL.md or skills/flux-drive/phases/*.md
set -euo pipefail

file_path="${TOOL_INPUT_FILE_PATH:-${TOOL_INPUT_file_path:-}}"
[[ -z "$file_path" ]] && exit 0

# Normalize to relative path within the plugin
plugin_root="${CLAUDE_PLUGIN_ROOT:-}"
[[ -z "$plugin_root" ]] && exit 0

# Check if the modified file is a flux-drive source file (but NOT the compact file itself)
case "$file_path" in
  */skills/flux-drive/SKILL.md|*/skills/flux-drive/phases/*.md|*/docs/spec/core/scoring.md|*/docs/spec/core/staging.md)
    # Check if SKILL-compact.md was also modified in this session (simple heuristic: check git status)
    compact_file="$(dirname "$file_path" | sed 's|/phases$||')/SKILL-compact.md"
    if [[ -f "$compact_file" ]]; then
      compact_status=$(cd "$(dirname "$compact_file")" && git diff --name-only HEAD -- "$(basename "$compact_file")" 2>/dev/null)
      if [[ -z "$compact_status" ]]; then
        echo "SKILL-compact.md may need updating — you changed a flux-drive source file. Run a diff check before committing."
      fi
    fi
    ;;
esac

exit 0
