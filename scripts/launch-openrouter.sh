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

# openrouter-dispatch bills per token. Subscription quota is the default path,
# so a key alone must never enable it: spending needs an explicit opt-in, a
# real key (not an unexpanded "${VAR}" placeholder), and a positive spend ceiling.
if [[ "${OPENROUTER_ALLOW_PAID_DISPATCH:-}" != "1" ]]; then
    echo "openrouter-dispatch MCP server disabled: paid dispatch needs OPENROUTER_ALLOW_PAID_DISPATCH=1." >&2
    exit 0
fi
if [[ "${OPENROUTER_API_KEY}" == *'${'* ]]; then
    echo "OPENROUTER_API_KEY is an unexpanded placeholder — openrouter-dispatch MCP server disabled." >&2
    exit 0
fi
if ! awk -v c="${OPENROUTER_SPEND_CEILING_USD:-0}" 'BEGIN{exit !(c+0>0)}'; then
    echo "OPENROUTER_SPEND_CEILING_USD must be > 0 — openrouter-dispatch MCP server disabled." >&2
    exit 0
fi

# Auto-build if dist/ missing
if [[ ! -f "${SERVER_DIR}/dist/index.js" ]]; then
    echo "Building openrouter-dispatch MCP server..." >&2
    (cd "$SERVER_DIR" && npm ci && npm run build) >&2
fi

exec node "${SERVER_DIR}/dist/index.js" "$@"
