#!/usr/bin/env bash
# detect-runtimes.sh — probe which peer agent runtimes are available for
# flux-melange --peers=auto (references/peer-runtimes.md).
#
# Emits ONE JSON object on stdout:
#   {"claude":{"available":true,"host":true},
#    "codex":{"available":true,"version":"codex-cli 0.144.4"},
#    "hermes":{"available":false,"version":null},
#    "kimi":{"available":true,"version":"kimi-cli 1.2.3"}}   (or "kimi-http k3")
#
# For CLI runtimes (codex, hermes) "available" means the binary is on PATH and
# answers --version. Auth state is NOT probed (auth prompts can hang a headless
# check); an unauthenticated CLI surfaces at probe time and the mirror degrades
# gracefully via the shim's SHIM-FAILURE contract.
#
# ADAPTIVE MODEL RESOLUTION. Each runtime also reports the model this environment
# can actually reach, plus why, so --peers=auto never silently mirrors on
# something other than the configured preference:
#   "model", "model_reason", "sandboxed"
# The ladders below MIRROR config/flux-melange/defaults.yaml § peers.runtimes —
# same arrangement kimi already uses, where the probe and the invoke wrapper
# apply one preference order so they can never disagree. Change both together.
#   codex   — gpt-6-astra needs Codex CLI >= 0.153.1 (the routing policy's
#             minimum_codex_version for the Astra profile); older CLIs fall back
#             to gpt-5.6-sol rather than failing at invoke time.
#   hermes  — deepseek/deepseek-v4.1-flash only exists on providers the user has
#             actually configured, so it is confirmed against
#             ~/.hermes/provider_models_cache.json; absent, the mirror falls back
#             to the CLI's own default (model null) instead of a model that would
#             resolve to something nobody chose.
#   kimi    — k3 on whichever lane probe_kimi selects.
#
# CONSENT. "sandboxed" reports whether a runtime confines its auto-approved tool
# use: codex --full-auto is workspace-write inside projectRoot; the kimi HTTP
# lane executes nothing locally. hermes --yolo and the kimi CLI lane run a
# tool-enabled agent in the project UNSANDBOXED. Detection never decides consent
# — charter shows it in the plan and honours peers.consent (peer-runtimes.md
# § Trust boundary). Naming a runtime explicitly is itself consent.
#
# kimi is a DUAL-LANE runtime, and scripts/kimi-peer-invoke.sh applies the same
# preference order at invoke time so probe and invoke always agree on the lane:
#   lane 1 (preferred) — the Kimi Code CLI on subscription OAuth: binary on
#     PATH (or at ~/.kimi-code/bin/kimi — installed outside PATH for
#     non-interactive shells, a known .zshrc-only PATH entry) plus a non-empty
#     ~/.kimi-code/credentials dir;
#   lane 2 (fallback) — HTTP POST to the Kimi coding endpoint, gated on
#     KIMI_API_KEY.
# Presence is data, not proof of auth; a bad/expired credential in either lane
# surfaces at invoke time as a SHIM-FAILURE.
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

# probe_kimi — dual-lane. CLI lane wins when the binary AND the OAuth
# credentials dir are both present; HTTP lane needs only KIMI_API_KEY.
probe_kimi() {
  local bin=""
  if command -v kimi >/dev/null 2>&1; then
    bin="kimi"
  elif [[ -x "${HOME}/.kimi-code/bin/kimi" ]]; then
    bin="${HOME}/.kimi-code/bin/kimi"
  fi
  if [[ -n "$bin" && -d "${HOME}/.kimi-code/credentials" ]] \
     && [[ -n "$(ls -A "${HOME}/.kimi-code/credentials" 2>/dev/null)" ]]; then
    local ver
    ver="$("$bin" --version 2>/dev/null | head -1 | tr -d '"' || true)"
    printf '{"available":true,"version":"kimi-cli %s"}' "${ver:-unknown}"
  elif [[ -n "${KIMI_API_KEY:-}" ]]; then
    printf '{"available":true,"version":"kimi-http %s"}' "${NTSMR_KIMI_MODEL:-k3}"
  else
    printf '{"available":false,"version":null}'
  fi
}

# ---------------------------------------------------------------------------
# Adaptive model resolution. Each emits: "model", "model_reason".
# A resolved model is a PREFERENCE that this environment can reach; it is never
# proof of entitlement or quota. Exhausted quota still surfaces at invoke time.

# version_at_least A B -> 0 when A >= B (sort -V, same test the dispatch wrapper uses)
version_at_least() {
  [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" == "$2" ]]
}

# codex: Astra needs CLI >= 0.153.1, else Sol. Mirrors run at medium — a mirror
# earns its keep on independent coverage, not depth, and sits on the Parley barrier.
resolve_codex() {
  command -v codex >/dev/null 2>&1 || { printf '"model":null,"model_reason":"codex not on PATH"'; return; }
  local raw ver
  raw="$(codex --version 2>/dev/null | head -1 || true)"
  ver="$(printf '%s' "$raw" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
  if [[ -n "$ver" ]] && version_at_least "$ver" "0.153.1"; then
    printf '"model":"gpt-6-astra","model_reason":"codex %s >= 0.153.1"' "$ver"
  else
    printf '"model":"gpt-5.6-sol","model_reason":"codex %s < 0.153.1, Astra unavailable"' "${ver:-unknown}"
  fi
}

# hermes: confirm the preferred model against the providers the user configured.
# Emits the provider too, because the id alone does not pin routing.
resolve_hermes() {
  command -v hermes >/dev/null 2>&1 || { printf '"model":null,"model_reason":"hermes not on PATH"'; return; }
  python3 - "$HOME/.hermes/provider_models_cache.json" <<'PYEOF' 2>/dev/null || printf '"model":null,"model_reason":"provider cache unreadable; using hermes CLI default"'
import json, sys
want = "deepseek/deepseek-v4.1-flash"
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    print('"model":null,"model_reason":"provider cache unreadable; using hermes CLI default"'); raise SystemExit(0)
for provider, info in data.items():
    if want in info.get("models", []):
        print(f'"model":"{want}","provider":"{provider}","model_reason":"confirmed on {provider}"')
        break
else:
    print('"model":null,"model_reason":"deepseek-v4.1-flash on no configured provider; using hermes CLI default"')
PYEOF
}

merge() { printf '%s' "${1%\}},$2}"; }   # splice resolver fields into a probe object

printf '{"claude":{"available":true,"host":true,"sandboxed":true},"codex":%s,"hermes":%s,"kimi":%s}\n' \
  "$(merge "$(probe codex)"  "$(resolve_codex),\"sandboxed\":true")" \
  "$(merge "$(probe hermes)" "$(resolve_hermes),\"sandboxed\":false")" \
  "$(merge "$(probe_kimi)"   "\"model\":\"k3\",\"model_reason\":\"lane selected by probe_kimi\",\"sandboxed\":false")"
