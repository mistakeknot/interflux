#!/usr/bin/env bash
# Launcher for exa-mcp-server: prefers a permanently-installed binary over `npx -y`.
#
# `npx -y exa-mcp-server` pays a ~190 ms npx-startup tax plus an unbundled
# dep-graph resolution cost on every session (measured ~616 ms cold-start,
# docs/research/mcp-cold-start-breakdown-2026-04-18.md R3). A global install
# (`npm install -g exa-mcp-server`) lets us exec the binary directly and skip
# that tax. We fall back to `npx -y` so zero-install setups keep working.
#
# Pattern established by interknow::qmd (scripts/launch-qmd.sh) and interject.
set -euo pipefail

# Global npm/bun bin dirs are not inherited by MCP server processes — prepend
# the usual locations so a permanently-installed exa-mcp-server is discoverable.
for _bindir in "$HOME/.npm-global/bin" "$HOME/.bun/bin" "$HOME/.local/bin"; do
    [[ -d "$_bindir" ]] && PATH="$_bindir:$PATH"
done

if [[ -z "${EXA_API_KEY:-}" ]]; then
    echo "EXA_API_KEY not set — Exa search MCP server disabled." >&2
    echo "Set EXA_API_KEY in your environment to enable web search in research agents." >&2
    # Exit 78 (EX_CONFIG) surfaces missing-prereq as a config error rather than a clean
    # shutdown (exit 0 masquerades as "running successfully" in Claude Code's plugin surface).
    exit 78
fi

# Fast path: permanently-installed binary, no npx tax.
if command -v exa-mcp-server &>/dev/null; then
    exec exa-mcp-server "$@"
fi

# Fallback: npx auto-fetch. Works without a global install but pays the npx tax
# on every launch. Install once to skip it: npm install -g exa-mcp-server
if command -v npx &>/dev/null; then
    echo "exa-mcp-server not installed globally — falling back to 'npx -y' (slower cold-start)." >&2
    echo "Install once to skip the npx tax: npm install -g exa-mcp-server" >&2
    exec npx -y exa-mcp-server "$@"
fi

echo "exa-mcp-server not found and npx unavailable — install Node.js, then: npm install -g exa-mcp-server" >&2
echo "interflux will work without Exa but web search will be unavailable." >&2
exit 78
