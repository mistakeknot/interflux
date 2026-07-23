#!/usr/bin/env bash
# kimi-peer-invoke.sh — HTTP transport for the flux-melange kimi peer runtime.
#
# kimi has no CLI binary, so this wrapper is its "invoke template" target: it
# reads a staged prompt file, POSTs it to the Kimi coding endpoint (OpenAI-
# compatible /chat/completions), and prints ONLY the final assistant message —
# mirroring codex's `-o {outfile}` contract so the melange shim extracts the
# final JSON object the same way for every runtime.
#
# Usage:
#   kimi-peer-invoke.sh <promptfile> [outfile]
#
#   <promptfile>  required — the shim-staged task.md (task + appended JSON schema)
#   [outfile]     optional — write the final message here (like codex -o);
#                 if omitted, the final message goes to stdout.
#
# Credentials (never hardcoded): read from env, falling back to ~/.hermes/.env.
#   KIMI_API_KEY    required (sk-kim..., the Kimi Coding Plan key)
#   KIMI_BASE_URL   default https://api.kimi.com/coding/v1
#   NTSMR_KIMI_MODEL default k3   (canonical coding-plan model id)
#
# K3 specifics baked in: temperature MUST be 1 (the model rejects others), and
# NO max_tokens cap is sent (K3 is reasoning-only — reasoning tokens count
# against the budget, so a small cap yields empty content).
#
# Exit non-zero with a diagnostic on stderr on any failure; the shim converts a
# failed invoke into its SHIM-FAILURE degradation path.
set -uo pipefail

PROMPTFILE="${1:-}"
OUTFILE="${2:-}"

if [[ -z "$PROMPTFILE" || ! -f "$PROMPTFILE" ]]; then
  echo "kimi-peer-invoke: promptfile not found: ${PROMPTFILE:-<none>}" >&2
  exit 2
fi

# Load shared env if the key is not already exported.
if [[ -z "${KIMI_API_KEY:-}" && -f "${HOME}/.hermes/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "${HOME}/.hermes/.env" 2>/dev/null || true
  set +a
fi

if [[ -z "${KIMI_API_KEY:-}" ]]; then
  echo "kimi-peer-invoke: KIMI_API_KEY not set (checked env + ~/.hermes/.env)" >&2
  exit 3
fi

BASE_URL="${KIMI_BASE_URL:-https://api.kimi.com/coding/v1}"
MODEL="${NTSMR_KIMI_MODEL:-k3}"

for dep in curl jq; do
  command -v "$dep" >/dev/null 2>&1 || { echo "kimi-peer-invoke: missing dependency: $dep" >&2; exit 4; }
done

# Build the request body. jq --rawfile reads the prompt as a single JSON string,
# so no shell-escaping hazard regardless of prompt content. temperature=1 is
# mandatory for K3; no max_tokens (reasoning-only model).
REQ_BODY="$(jq -n \
  --arg model "$MODEL" \
  --rawfile content "$PROMPTFILE" \
  '{
     model: $model,
     temperature: 1,
     messages: [ { role: "user", content: $content } ]
   }')"

RESP="$(curl -sS --fail-with-body -m 590 \
  -X POST "${BASE_URL%/}/chat/completions" \
  -H "Authorization: Bearer ${KIMI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$REQ_BODY" 2>/tmp/kimi-peer-curl.err)" || {
    echo "kimi-peer-invoke: request failed: $(head -c 400 /tmp/kimi-peer-curl.err 2>/dev/null)" >&2
    exit 5
  }

# Extract the final assistant message content.
MSG="$(printf '%s' "$RESP" | jq -er '.choices[0].message.content // empty' 2>/dev/null || true)"

if [[ -z "$MSG" ]]; then
  echo "kimi-peer-invoke: empty/unparseable response: $(printf '%s' "$RESP" | head -c 400)" >&2
  exit 6
fi

if [[ -n "$OUTFILE" ]]; then
  printf '%s' "$MSG" > "$OUTFILE"
else
  printf '%s' "$MSG"
fi
