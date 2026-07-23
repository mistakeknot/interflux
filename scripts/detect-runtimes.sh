#!/usr/bin/env bash
# detect-runtimes.sh — probe which peer agent runtimes are available for
# flux-melange --peers=auto (references/peer-runtimes.md).
#
# Emits ONE JSON object on stdout:
#   {"claude":{"available":true,"host":true},
#    "codex":{"available":true,"version":"codex-cli 0.144.4"},
#    "hermes":{"available":false,"version":null},
#    "kimi":{"available":true,"version":"kimi-http k3"}}
#
# For CLI runtimes (codex, hermes) "available" means the binary is on PATH and
# answers --version. Auth state is NOT probed (auth prompts can hang a headless
# check); an unauthenticated CLI surfaces at probe time and the mirror degrades
# gracefully via the shim's SHIM-FAILURE contract.
#
# kimi is an HTTP runtime with NO CLI binary — it POSTs to the Kimi coding
# endpoint via scripts/kimi-peer-invoke.sh. It has no `--version` to answer, so
# its probe checks for a credential (KIMI_API_KEY) instead of `command -v`.
# Same posture as the CLIs: presence of the key is data, not proof of auth; a
# bad/expired key surfaces at invoke time as a SHIM-FAILURE.
#
# Exit code is always 0 — absence is data, not an error.
set -uo pipefail

# Best-effort: load the shared env file so KIMI_API_KEY is visible even when the
# caller has not sourced it. Silent if absent; never fails the probe.
if [[ -z "${KIMI_API_KEY:-}" && -f "${HOME}/.hermes/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "${HOME}/.hermes/.env" 2>/dev/null || true
  set +a
fi

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

# probe_kimi — HTTP runtime, no binary. Available iff a credential is present.
probe_kimi() {
  if [[ -n "${KIMI_API_KEY:-}" ]]; then
    printf '{"available":true,"version":"kimi-http %s"}' "${NTSMR_KIMI_MODEL:-k3}"
  else
    printf '{"available":false,"version":null}'
  fi
}

printf '{"claude":{"available":true,"host":true},"codex":%s,"hermes":%s,"kimi":%s}\n' \
  "$(probe codex)" "$(probe hermes)" "$(probe_kimi)"
