#!/usr/bin/env bash
set -uo pipefail
trap 'exit 0' ERR
# interflux session-start hook — source interbase, read budget signal, emit status
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_INPUT=$(cat)   # consume stdin first — session_id is here

# Source interbase (live or stub)
source "$HOOK_DIR/interbase-stub.sh"

# Emit ecosystem status (no-op in stub mode)
ib_session_status

# --- First-run diagnostic (runs once after install) ---
_if_init_dir="${HOME}/.config/interflux"
_if_init_flag="${_if_init_dir}/.initialized"
if [[ ! -f "$_if_init_flag" ]]; then
  mkdir -p "$_if_init_dir"
  _if_missing=()
  command -v jq &>/dev/null || _if_missing+=("jq: required by interflux hooks (install via your package manager)")
  command -v qmd &>/dev/null || _if_missing+=("qmd: enables semantic doc search (install with: bun install -g qmd)")
  [[ -n "${EXA_API_KEY:-}" ]] || _if_missing+=("EXA_API_KEY: enables web search in research agents (set in your shell profile)")
  if [[ ${#_if_missing[@]} -gt 0 ]]; then
    echo "[interflux] First-run setup check — optional dependencies:" >&2
    for _if_item in "${_if_missing[@]}"; do
      echo "  - $_if_item" >&2
    done
    echo "[interflux] interflux works without these, but some features will be degraded." >&2
  fi
  touch "$_if_init_flag"
fi

# --- Budget signal reading (requires jq) ---
if ! command -v jq &>/dev/null; then
  # Cannot parse session input or budget files without jq — skip gracefully
  exit 0
fi

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
      # Validate _if_pct strictly: must be a non-negative numeric (integer or decimal <= 100).
      # A malformed payload coercing to 0 produces awk computing full_budget as "remaining"
      # — phantom headroom in flux-drive dispatch. On invalid pct, skip the export entirely.
      if [[ "$_if_pct" =~ ^[0-9]+(\.[0-9]+)?$ ]] && (( $(awk "BEGIN{print ($_if_pct >= 0 && $_if_pct <= 100)}") )); then
        _if_budget="${INTERSTAT_TOKEN_BUDGET:-500000}"
        [[ "$_if_budget" =~ ^[0-9]+$ ]] || _if_budget=500000
        _if_remaining=$(awk "BEGIN{printf \"%d\", $_if_budget * (100 - $_if_pct) / 100}" 2>/dev/null || echo "")
        if [[ -n "$_if_remaining" && "$_if_remaining" -gt 0 && -n "${CLAUDE_ENV_FILE:-}" ]]; then
          echo "export FLUX_BUDGET_REMAINING=${_if_remaining}" >> "$CLAUDE_ENV_FILE"
        fi
      else
        echo "session-start: ignoring malformed context_pct '$_if_pct' (expected 0-100)" >&2
      fi
    fi
  fi
fi

# --- FluxBench model awareness (lightweight, no API calls) ---
_if_registry="${HOOK_DIR}/../config/flux-drive/model-registry.yaml"
if [[ -f "$_if_registry" ]] && command -v python3 &>/dev/null; then
  export _FB_REGISTRY_PATH="$_if_registry"
  _if_awareness=$(python3 -c "
import yaml, sys, os
try:
    with open(os.environ['_FB_REGISTRY_PATH']) as f:
        d = yaml.safe_load(f)
    models = d.get('models', {}) or {}
    msgs = []

    # Check for models needing requalification
    requalify = [k for k, v in models.items() if isinstance(v, dict) and v.get('requalification_needed')]
    if requalify:
        names = ', '.join(requalify[:3])
        msgs.append(f'[fluxbench] {len(requalify)} model(s) need requalification: {names}')

    # Surface new models from interrank not yet in registry
    # Read task queries from budget config if available
    budget_path = os.path.join(os.path.dirname(os.environ['_FB_REGISTRY_PATH']), 'budget.yaml')
    known_slugs = set(models.keys()) if isinstance(models, dict) else set()
    try:
        with open(budget_path) as f:
            budget = yaml.safe_load(f) or {}
        # interrank recommend_model results are checked at discovery time,
        # but we can flag models that were discovered but never qualified
        candidates = [k for k, v in models.items()
                      if isinstance(v, dict) and v.get('status') == 'candidate'
                      and not v.get('fluxbench')]
        if candidates:
            names = ', '.join(candidates[:3])
            suffix = f' (+{len(candidates)-3} more)' if len(candidates) > 3 else ''
            msgs.append(f'[fluxbench] {len(candidates)} unqualified candidate(s): {names}{suffix}')
    except Exception:
        pass

    for msg in msgs:
        print(msg)
except Exception:
    pass
" 2>/dev/null) || _if_awareness=""
  unset _FB_REGISTRY_PATH
  [[ -n "$_if_awareness" ]] && echo "$_if_awareness" >&2
fi
