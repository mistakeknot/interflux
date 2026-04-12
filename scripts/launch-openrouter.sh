#!/usr/bin/env bash
# Launcher for openrouter-dispatch MCP server.
# Needs Node.js and OPENROUTER_API_KEY to function.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="${SCRIPT_DIR}/../mcp-servers/openrouter-dispatch"

if ! command -v node &>/dev/null; then
    echo "Node.js not found — openrouter-dispatch MCP server disabled." >&2
    exit 0
fi

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
    echo "OPENROUTER_API_KEY not set — openrouter-dispatch MCP server disabled." >&2
    exit 0
fi

# Auto-build if dist/ missing
if [[ ! -f "${SERVER_DIR}/dist/index.js" ]]; then
    echo "Building openrouter-dispatch MCP server..." >&2
    (cd "$SERVER_DIR" && npm ci && npm run build) >&2
fi

exec node "${SERVER_DIR}/dist/index.js" "$@"
