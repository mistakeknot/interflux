#!/usr/bin/env bash
# kimi-peer-invoke.sh — dual-lane transport for the flux-melange kimi peer
# runtime. Whatever the lane, it ends the same way: ONLY the final assistant
# message is written, mirroring codex's `-o {outfile}` contract so the melange
# shim extracts the final JSON object the same way for every runtime.
#
# LANE 1 (preferred) — the Kimi Code CLI on subscription OAuth. Runs
#   `kimi --output-format stream-json -p <prompt>` headless (no API key) and
#   extracts the LAST role=assistant JSONL row as the final message. Verified
#   2026-07-27 (mk-2xg5): `-p` mode auto-approves regular tool calls (a
#   probe-shaped file-read ran without an approval hang) and REJECTS
#   --auto/--yolo as conflicting flags. TRUST NOTE vs the HTTP lane: this lane
#   runs a TOOL-ENABLED agent in the CWD, UNSANDBOXED (hermes --yolo class),
#   and the user's kimi hooks (e.g. UserPromptSubmit) fire inside the run and
#   inject their context.
#
# LANE 2 (fallback) — POST the prompt to the Kimi coding endpoint (OpenAI-
#   compatible /chat/completions) with KIMI_API_KEY. No local execution.
#
# Lane selection mirrors detect-runtimes.sh:probe_kimi exactly, so probe and
# invoke always agree: CLI iff the binary exists (PATH, else
# ~/.kimi-code/bin/kimi — a known .zshrc-only PATH entry that non-interactive
# shells miss) AND ~/.kimi-code/credentials is a non-empty dir; else HTTP iff
# KIMI_API_KEY is set.
#
# Usage:
#   kimi-peer-invoke.sh <promptfile> [outfile]
#
#   <promptfile>  required — the shim-staged task.md (task + appended JSON schema)
#   [outfile]     optional — write the final message here (like codex -o);
#                 if omitted, the final message goes to stdout.
#
# Env (credentials never hardcoded; HTTP creds fall back to ~/.hermes/.env):
#   KIMI_PEER_LANE   auto|cli|http (default auto — the preference order above)
#   KIMI_PEER_TIMEOUT seconds, both lanes (default 590)
#   KIMI_API_KEY     HTTP lane (sk-kim..., the Kimi Coding Plan key)
#   KIMI_BASE_URL    HTTP lane, default https://api.kimi.com/coding/v1
#   NTSMR_KIMI_MODEL default k3 (canonical coding-plan model id)
#   KIMI_CLI_MODEL   CLI lane model ALIAS, default kimi-code/${NTSMR_KIMI_MODEL}.
#                    The bare id 'k3' is config.invalid on the CLI, and the '/'
#                    in the alias would fail the peer-model regex
#                    (^[A-Za-z0-9._:-]{1,64}$) — which is why the mapping lives
#                    HERE and config keeps the regex-safe `model: k3`.
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

# ---------------------------------------------------------------------------
# Lane selection (must stay in lockstep with detect-runtimes.sh:probe_kimi).
KIMI_BIN=""
if command -v kimi >/dev/null 2>&1; then
  KIMI_BIN="$(command -v kimi)"
elif [[ -x "${HOME}/.kimi-code/bin/kimi" ]]; then
  KIMI_BIN="${HOME}/.kimi-code/bin/kimi"
fi

cli_viable=false
if [[ -n "$KIMI_BIN" && -d "${HOME}/.kimi-code/credentials" ]] \
   && [[ -n "$(ls -A "${HOME}/.kimi-code/credentials" 2>/dev/null)" ]]; then
  cli_viable=true
fi

LANE="${KIMI_PEER_LANE:-auto}"
case "$LANE" in
  cli)
    if [[ "$cli_viable" != true ]]; then
      echo "kimi-peer-invoke: KIMI_PEER_LANE=cli but no viable CLI (need the kimi binary + a non-empty ~/.kimi-code/credentials)" >&2
      exit 3
    fi
    ;;
  http) cli_viable=false ;;
  auto) ;;
  *)
    echo "kimi-peer-invoke: invalid KIMI_PEER_LANE '$LANE' (auto|cli|http)" >&2
    exit 2
    ;;
esac

TIMEOUT_S="${KIMI_PEER_TIMEOUT:-590}"

# ---------------------------------------------------------------------------
# LANE 1: Kimi Code CLI (subscription OAuth).
if [[ "$cli_viable" == true ]]; then
  command -v jq >/dev/null 2>&1 || { echo "kimi-peer-invoke: missing dependency: jq" >&2; exit 4; }
  CLI_MODEL="${KIMI_CLI_MODEL:-kimi-code/${NTSMR_KIMI_MODEL:-k3}}"

  RAW="$(mktemp)" ERR="$(mktemp)"
  trap 'rm -f "$RAW" "$ERR"' EXIT

  # -p is the CLI's headless prompt mode: it auto-approves regular tool calls
  # and refuses --auto/--yolo. `timeout` is guarded — macOS lacks it without
  # coreutils; the melange shim's own Bash timeout still bounds the call.
  rc=0
  if command -v timeout >/dev/null 2>&1; then
    timeout "$TIMEOUT_S" "$KIMI_BIN" -m "$CLI_MODEL" --output-format stream-json \
      -p "$(cat "$PROMPTFILE")" >"$RAW" 2>"$ERR" || rc=$?
  else
    "$KIMI_BIN" -m "$CLI_MODEL" --output-format stream-json \
      -p "$(cat "$PROMPTFILE")" >"$RAW" 2>"$ERR" || rc=$?
  fi
  if [[ $rc -ne 0 ]]; then
    echo "kimi-peer-invoke: CLI lane failed (rc=$rc): $(tail -c 400 "$ERR" 2>/dev/null)" >&2
    exit 5
  fi

  # stream-json emits JSONL; the final message is the LAST role=assistant row
  # (earlier assistant rows carry hook dumps and intermediate turns).
  MSG="$(jq -rs '[ .[] | select(.role=="assistant") ] | last | .content // empty' <"$RAW" 2>/dev/null || true)"
  if [[ -z "$MSG" ]]; then
    echo "kimi-peer-invoke: CLI lane produced no assistant message: $(tail -c 400 "$RAW" 2>/dev/null)" >&2
    exit 6
  fi

  if [[ -n "$OUTFILE" ]]; then
    printf '%s' "$MSG" > "$OUTFILE"
  else
    printf '%s' "$MSG"
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# LANE 2: HTTP POST with KIMI_API_KEY.
if [[ -z "${KIMI_API_KEY:-}" ]]; then
  echo "kimi-peer-invoke: no viable lane — CLI absent/uncredentialed (need the kimi binary + ~/.kimi-code/credentials) and KIMI_API_KEY not set (checked env + ~/.hermes/.env)" >&2
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

RESP="$(curl -sS --fail-with-body -m "$TIMEOUT_S" \
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
