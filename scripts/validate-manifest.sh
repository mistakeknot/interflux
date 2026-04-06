#!/usr/bin/env bash
# validate-manifest.sh — Check plugin.json against directory contents
# Usage: validate-manifest.sh [--fix]
# Output: list of discrepancies (exit 0 = in sync, exit 1 = drift detected)
# With --fix: update plugin.json to match directory contents (preserves mcpServers, metadata)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST="$PLUGIN_DIR/.claude-plugin/plugin.json"
FIX=false

[[ "${1:-}" == "--fix" ]] && FIX=true

if [[ ! -f "$MANIFEST" ]]; then
    echo "Error: $MANIFEST not found" >&2
    exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq required" >&2
    exit 2
fi

errors=0

# --- Skills ---
# Scan for skill directories (contain SKILL.md, exclude deprecated)
DISK_SKILLS=()
for skill_dir in "$PLUGIN_DIR"/skills/*/SKILL.md; do
    [[ -f "$skill_dir" ]] || continue
    dir=$(dirname "$skill_dir")
    # Skip if SKILL.md contains DEPRECATED in first 5 lines
    if head -5 "$skill_dir" | grep -qi "deprecated"; then
        continue
    fi
    rel="./${dir#$PLUGIN_DIR/}"
    DISK_SKILLS+=("$rel")
done

MANIFEST_SKILLS=$(jq -r '.skills[]' "$MANIFEST" 2>/dev/null | sort)
DISK_SKILLS_SORTED=$(printf '%s\n' "${DISK_SKILLS[@]}" | sort)

MISSING_SKILLS=$(comm -23 <(echo "$DISK_SKILLS_SORTED") <(echo "$MANIFEST_SKILLS"))
EXTRA_SKILLS=$(comm -13 <(echo "$DISK_SKILLS_SORTED") <(echo "$MANIFEST_SKILLS"))

if [[ -n "$MISSING_SKILLS" ]]; then
    echo "Skills on disk but NOT in manifest:"
    echo "$MISSING_SKILLS" | sed 's/^/  + /'
    errors=$((errors + 1))
fi
if [[ -n "$EXTRA_SKILLS" ]]; then
    echo "Skills in manifest but NOT on disk:"
    echo "$EXTRA_SKILLS" | sed 's/^/  - /'
    errors=$((errors + 1))
fi

# --- Commands ---
DISK_CMDS=()
for cmd in "$PLUGIN_DIR"/commands/*.md; do
    [[ -f "$cmd" ]] || continue
    rel="./${cmd#$PLUGIN_DIR/}"
    DISK_CMDS+=("$rel")
done

MANIFEST_CMDS=$(jq -r '.commands[]' "$MANIFEST" 2>/dev/null | sort)
DISK_CMDS_SORTED=$(printf '%s\n' "${DISK_CMDS[@]}" | sort)

MISSING_CMDS=$(comm -23 <(echo "$DISK_CMDS_SORTED") <(echo "$MANIFEST_CMDS"))
EXTRA_CMDS=$(comm -13 <(echo "$DISK_CMDS_SORTED") <(echo "$MANIFEST_CMDS"))

if [[ -n "$MISSING_CMDS" ]]; then
    echo "Commands on disk but NOT in manifest:"
    echo "$MISSING_CMDS" | sed 's/^/  + /'
    errors=$((errors + 1))
fi
if [[ -n "$EXTRA_CMDS" ]]; then
    echo "Commands in manifest but NOT on disk:"
    echo "$EXTRA_CMDS" | sed 's/^/  - /'
    errors=$((errors + 1))
fi

# --- Agents ---
DISK_AGENTS=()
for agent in "$PLUGIN_DIR"/agents/*/*.md; do
    [[ -f "$agent" ]] || continue
    base=$(basename "$agent")
    # Skip non-agent files
    [[ "$base" == "measurement.md" ]] && continue
    [[ "$base" == "README.md" ]] && continue
    rel="./${agent#$PLUGIN_DIR/}"
    DISK_AGENTS+=("$rel")
done

MANIFEST_AGENTS=$(jq -r '.agents[]' "$MANIFEST" 2>/dev/null | sort)
DISK_AGENTS_SORTED=$(printf '%s\n' "${DISK_AGENTS[@]}" | sort)

MISSING_AGENTS=$(comm -23 <(echo "$DISK_AGENTS_SORTED") <(echo "$MANIFEST_AGENTS"))
EXTRA_AGENTS=$(comm -13 <(echo "$DISK_AGENTS_SORTED") <(echo "$MANIFEST_AGENTS"))

if [[ -n "$MISSING_AGENTS" ]]; then
    echo "Agents on disk but NOT in manifest:"
    echo "$MISSING_AGENTS" | sed 's/^/  + /'
    errors=$((errors + 1))
fi
if [[ -n "$EXTRA_AGENTS" ]]; then
    echo "Agents in manifest but NOT on disk:"
    echo "$EXTRA_AGENTS" | sed 's/^/  - /'
    errors=$((errors + 1))
fi

# --- Fix mode ---
if [[ "$FIX" == true && "$errors" -gt 0 ]]; then
    echo ""
    echo "Fixing manifest..."

    # Build new arrays
    SKILLS_JSON=$(printf '%s\n' "${DISK_SKILLS[@]}" | jq -R . | jq -s .)
    CMDS_JSON=$(printf '%s\n' "${DISK_CMDS[@]}" | jq -R . | jq -s .)
    AGENTS_JSON=$(printf '%s\n' "${DISK_AGENTS[@]}" | jq -R . | jq -s .)

    # Update manifest preserving all other fields
    jq --argjson skills "$SKILLS_JSON" \
       --argjson cmds "$CMDS_JSON" \
       --argjson agents "$AGENTS_JSON" \
       '.skills = $skills | .commands = $cmds | .agents = $agents' \
       "$MANIFEST" > "$MANIFEST.tmp" && mv "$MANIFEST.tmp" "$MANIFEST"

    echo "Updated $MANIFEST"
    exit 0
fi

# --- Summary ---
if [[ "$errors" -eq 0 ]]; then
    echo "Manifest in sync: $(echo "$MANIFEST_SKILLS" | wc -w) skills, $(echo "$MANIFEST_CMDS" | wc -l) commands, $(echo "$MANIFEST_AGENTS" | wc -l) agents"
    exit 0
else
    echo ""
    echo "$errors discrepancies found. Run with --fix to update manifest."
    exit 1
fi
