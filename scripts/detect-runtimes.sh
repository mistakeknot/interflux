#!/usr/bin/env bash
# detect-runtimes.sh — probe which peer agent runtimes are available for
# flux-melange --peers=auto (references/peer-runtimes.md).
#
# Emits ONE JSON object on stdout:
#   {"claude":{"available":true,"host":true},
#    "codex":{"available":true,"version":"codex-cli 0.144.4"},
#    "hermes":{"available":false,"version":null}}
#
# "Available" means the CLI is on PATH and answers --version. Auth state is
# NOT probed here (auth prompts can hang a headless check); an unauthenticated
# CLI surfaces at probe time and the mirror degrades gracefully via the shim's
# SHIM-FAILURE contract. Exit code is always 0 — absence is data, not an error.
set -uo pipefail

probe() {
  local bin="$1"
  local ver=""
  if command -v "$bin" >/dev/null 2>&1; then
    ver="$("$bin" --version 2>/dev/null | head -1 | tr -d '"' || true)"
    printf '{"available":true,"version":"%s"}' "${ver}"
  else
    printf '{"available":false,"version":null}'
  fi
}

printf '{"claude":{"available":true,"host":true},"codex":%s,"hermes":%s}\n' \
  "$(probe codex)" "$(probe hermes)"
