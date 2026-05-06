#!/usr/bin/env bash
# teams_detect.sh — detect whether Claude Code agent-teams (--teams) is available.
#
# Exit codes:
#   0 → available
#   1 → unavailable (env disabled, version too old, or version unparseable)
#
# Stdout: exactly one of:
#   "available" | "disabled" | "version_too_old" | "version_unparseable"
#
# Stderr: human-readable detail (only on non-available paths).
#
# Minimum Claude Code version: 2.1.32 (per https://code.claude.com/docs/en/agent-teams).

set -u

MIN_VERSION="2.1.32"

# 1. Env gate
if [[ "${CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS:-0}" != "1" ]]; then
    echo "disabled"
    echo "teams_detect: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS!=1; agent teams disabled" >&2
    exit 1
fi

# 2. claude --version (graceful if not on PATH)
v_raw=$(claude --version 2>/dev/null || true)
if [[ -z "$v_raw" ]]; then
    echo "version_unparseable"
    echo "teams_detect: 'claude --version' returned empty (not on PATH or failed)" >&2
    exit 1
fi
v=$(echo "$v_raw" | awk '{print $1}')
if [[ -z "$v" || ! "$v" =~ ^[0-9] ]]; then
    echo "version_unparseable"
    echo "teams_detect: could not parse version from: $v_raw" >&2
    exit 1
fi

# 3. Strip suffix (e.g., 2.1.32-beta or 2.1.32+build.5 → 2.1.32) for sort -V comparison.
#    sort -V handles suffixes correctly when they're after a hyphen, but a "+build" suffix
#    confuses the lexicographic fallback in some BSD sorts. Normalize to MAJOR.MINOR.PATCH.
v_norm=$(echo "$v" | sed -E 's/[+-].*//')
if [[ ! "$v_norm" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "version_unparseable"
    echo "teams_detect: normalized version '$v_norm' (from '$v') not in MAJOR.MINOR.PATCH form" >&2
    exit 1
fi

# 4. Compare against minimum
lowest=$(printf '%s\n%s\n' "$MIN_VERSION" "$v_norm" | sort -V | head -1)
if [[ "$lowest" == "$MIN_VERSION" ]]; then
    echo "available"
    exit 0
fi
echo "version_too_old"
echo "teams_detect: claude $v_norm < required $MIN_VERSION" >&2
exit 1
