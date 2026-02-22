#!/usr/bin/env bash
# Write per-agent capability files for interlock registration.
# Reads agentCapabilities from plugin.json, extracts caps for each agent,
# and writes to ~/.config/clavain/capabilities-<agent-name>.json
set -euo pipefail

PLUGIN_JSON="${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json"
[[ -f "$PLUGIN_JSON" ]] || exit 0

CAPS_DIR="${HOME}/.config/clavain"
mkdir -p "$CAPS_DIR"

# Extract agent paths from agentCapabilities keys and write per-agent files
jq -r '.agentCapabilities // {} | to_entries[] | .key' "$PLUGIN_JSON" 2>/dev/null | while IFS= read -r agent_path; do
    # Derive agent name from path: ./agents/review/fd-architecture.md -> fd-architecture
    agent_name=$(basename "$agent_path" .md)
    caps=$(jq -c --arg path "$agent_path" '.agentCapabilities[$path] // []' "$PLUGIN_JSON" 2>/dev/null)
    if [[ -n "$caps" ]] && [[ "$caps" != "null" ]] && [[ "$caps" != "[]" ]]; then
        echo "$caps" > "${CAPS_DIR}/capabilities-${agent_name}.json"
    fi
done
