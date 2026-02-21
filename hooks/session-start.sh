#!/usr/bin/env bash
set -euo pipefail
# interflux session-start hook — source interbase, read budget signal, emit status
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_INPUT=$(cat)   # consume stdin first — session_id is here

# Source interbase (live or stub)
source "$HOOK_DIR/interbase-stub.sh"

# Emit ecosystem status (no-op in stub mode)
ib_session_status

# Read interstat budget signal if available (always-on, not sprint-only)
_if_session_id=$(printf '%s' "$HOOK_INPUT" | jq -r '.session_id // empty' 2>/dev/null)

_if_interband_root="${INTERBAND_ROOT:-${HOME}/.interband}"

# Source interband for envelope validation
_if_interband_lib=""
_if_repo_root="$(git -C "$HOOK_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
for _if_lib_candidate in \
    "${INTERBAND_LIB:-}" \
    "${HOOK_DIR}/../../../infra/interband/lib/interband.sh" \
    "${HOOK_DIR}/../../../interband/lib/interband.sh" \
    "${_if_repo_root}/../interband/lib/interband.sh" \
    "${HOME}/.local/share/interband/lib/interband.sh"; do
  [[ -n "$_if_lib_candidate" && -f "$_if_lib_candidate" ]] && _if_interband_lib="$_if_lib_candidate" && break
done

if [[ -n "$_if_session_id" && -z "${FLUX_BUDGET_REMAINING:-}" ]]; then
  _if_budget_file="${_if_interband_root}/interstat/budget/${_if_session_id}.json"
  if [[ -f "$_if_budget_file" ]]; then
    # Use interband_read_payload for envelope validation if available
    _if_pct=""
    if [[ -n "$_if_interband_lib" ]]; then
      source "$_if_interband_lib" || true
      _if_payload=$(interband_read_payload "$_if_budget_file" 2>/dev/null) || _if_payload=""
      if [[ -n "$_if_payload" ]]; then
        _if_pct=$(printf '%s' "$_if_payload" | jq -r '.pct_consumed // empty' 2>/dev/null)
      fi
    else
      # Fallback: raw jq if interband.sh not available
      _if_pct=$(jq -r '.payload.pct_consumed // empty' "$_if_budget_file" 2>/dev/null)
    fi

    if [[ -n "$_if_pct" ]]; then
      _if_pct_int="${_if_pct%.*}"
      [[ "$_if_pct_int" =~ ^[0-9]+$ ]] || _if_pct_int=0
      # Convert percentage consumed to remaining tokens estimate
      _if_budget="${INTERSTAT_TOKEN_BUDGET:-500000}"
      [[ "$_if_budget" =~ ^[0-9]+$ ]] || _if_budget=500000
      _if_remaining=$(awk "BEGIN{printf \"%d\", $_if_budget * (100 - $_if_pct) / 100}" 2>/dev/null || echo "")
      if [[ -n "$_if_remaining" && "$_if_remaining" -gt 0 && -n "${CLAUDE_ENV_FILE:-}" ]]; then
        echo "export FLUX_BUDGET_REMAINING=${_if_remaining}" >> "$CLAUDE_ENV_FILE"
      fi
    fi
  fi
fi
