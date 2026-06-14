#!/usr/bin/env bash
# flux-dispatch.sh — mechanical admission control for agent dispatch (issue #5).
#
# The flux-drive concurrency cap (MAX_CONCURRENT_AGENTS) was previously prose the
# orchestrating LLM was asked to honor — nothing stopped it emitting every Agent
# call at once and breaching the cap. This script turns the cap into a real
# semaphore: a flock-guarded slot file under {OUTPUT_DIR}/.dispatch-slots holds at
# most N tokens. `acquire` blocks until a slot is free; `release` frees one.
#
# Usage:
#   flux-dispatch.sh acquire <output_dir> [max] [timeout_secs]
#       Block until a dispatch slot is free, then claim it. Prints "ok <in_flight>/<max>".
#       Exit 0 on slot claimed, 1 on timeout (no slot freed within timeout_secs).
#   flux-dispatch.sh release <output_dir>
#       Release one slot. Exit 0 (idempotent: never drops below zero).
#   flux-dispatch.sh count <output_dir>
#       Print current in-flight count. Exit 0.
#   flux-dispatch.sh wait <output_dir> <output_file> [max] [timeout_secs]
#       Convenience for the release path: block until <output_file> (an agent's
#       terminal .md) appears, then release one slot. Exit 0 on appearance,
#       1 on timeout (slot is still released so the cap cannot deadlock).
#   flux-dispatch.sh reset <output_dir> [max]
#       (Re)initialize the slot file to zero in-flight. Call once before a wave.
#
# Resolution order for <max> (highest precedence first):
#   1. explicit <max> argument
#   2. $MAX_CONCURRENT_AGENTS env var
#   3. budget.yaml `dispatch.max_concurrent_agents`
#   4. default 6
#
# The slot file format is a single integer line: the current in-flight count.
# fd 204: dispatch slots lock domain — see scripts/README.md § flock fd allocation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUDGET_CONFIG="${BUDGET_CONFIG:-${SCRIPT_DIR}/../config/flux-drive/budget.yaml}"

DEFAULT_MAX=6
POLL_INTERVAL=1     # seconds between slot-availability retries
DEFAULT_TIMEOUT=600 # seconds an acquire will block before giving up

# Read dispatch.max_concurrent_agents from budget.yaml without a YAML dependency.
# Falls back silently to "" if the key/file is missing.
_budget_max() {
    [[ -f "$BUDGET_CONFIG" ]] || return 0
    python3 - "$BUDGET_CONFIG" <<'PY' 2>/dev/null || true
import sys
try:
    import yaml
except Exception:
    sys.exit(0)
try:
    with open(sys.argv[1]) as fh:
        data = yaml.safe_load(fh) or {}
except Exception:
    sys.exit(0)
val = (data.get("dispatch") or {}).get("max_concurrent_agents")
if isinstance(val, int) and val > 0:
    print(val)
PY
}

# Resolve the effective cap. Arg ($1) wins, then env, then budget, then default.
resolve_max() {
    local arg="${1:-}"
    if [[ -n "$arg" && "$arg" =~ ^[0-9]+$ && "$arg" -gt 0 ]]; then
        echo "$arg"; return 0
    fi
    if [[ -n "${MAX_CONCURRENT_AGENTS:-}" && "${MAX_CONCURRENT_AGENTS}" =~ ^[0-9]+$ && "${MAX_CONCURRENT_AGENTS}" -gt 0 ]]; then
        echo "${MAX_CONCURRENT_AGENTS}"; return 0
    fi
    local b
    b="$(_budget_max)"
    if [[ -n "$b" && "$b" =~ ^[0-9]+$ && "$b" -gt 0 ]]; then
        echo "$b"; return 0
    fi
    echo "$DEFAULT_MAX"
}

_slot_file() { echo "${1%/}/.dispatch-slots"; }
_lock_file() { echo "${1%/}/.dispatch-slots.lock"; }

# Read the current count (0 if file missing/empty/garbage).
_read_count() {
    local f="$1" v
    v="$(cat "$f" 2>/dev/null || true)"
    [[ "$v" =~ ^[0-9]+$ ]] && echo "$v" || echo 0
}

cmd="${1:?Usage: flux-dispatch.sh <acquire|release|count|wait|reset> <output_dir> ...}"
shift || true

case "$cmd" in
  reset)
    output_dir="${1:?reset requires <output_dir>}"; shift || true
    mkdir -p "$output_dir"
    slot="$(_slot_file "$output_dir")"; lock="$(_lock_file "$output_dir")"
    (
      flock -x 204
      echo 0 > "$slot"
    ) 204>"$lock"
    echo "ok 0/$(resolve_max "${1:-}")"
    ;;

  count)
    output_dir="${1:?count requires <output_dir>}"
    slot="$(_slot_file "$output_dir")"; lock="$(_lock_file "$output_dir")"
    mkdir -p "$output_dir"
    (
      flock -s 204
      _read_count "$slot"
    ) 204>"$lock"
    ;;

  acquire)
    output_dir="${1:?acquire requires <output_dir>}"; shift || true
    max="$(resolve_max "${1:-}")"; shift || true
    timeout="${1:-$DEFAULT_TIMEOUT}"
    mkdir -p "$output_dir"
    slot="$(_slot_file "$output_dir")"; lock="$(_lock_file "$output_dir")"
    deadline=$(( $(date +%s) + timeout ))
    while :; do
        claimed=""
        # Critical section: read count, claim a slot if one is free.
        (
          flock -x 204
          cur="$(_read_count "$slot")"
          if (( cur < max )); then
              echo $(( cur + 1 )) > "$slot"
              exit 0   # signal "claimed" to parent via subshell exit
          fi
          exit 10      # signal "full"
        ) 204>"$lock" && claimed=1 || claimed=""
        if [[ -n "$claimed" ]]; then
            echo "ok $(_read_count "$slot")/$max"
            exit 0
        fi
        if (( $(date +%s) >= deadline )); then
            echo "timeout $(_read_count "$slot")/$max" >&2
            exit 1
        fi
        sleep "$POLL_INTERVAL"
    done
    ;;

  release)
    output_dir="${1:?release requires <output_dir>}"
    slot="$(_slot_file "$output_dir")"; lock="$(_lock_file "$output_dir")"
    mkdir -p "$output_dir"
    (
      flock -x 204
      cur="$(_read_count "$slot")"
      if (( cur > 0 )); then
          echo $(( cur - 1 )) > "$slot"
      else
          echo 0 > "$slot"
      fi
    ) 204>"$lock"
    echo "ok $(_read_count "$slot")"
    ;;

  wait)
    output_dir="${1:?wait requires <output_dir>}"; shift || true
    output_file="${1:?wait requires <output_file>}"; shift || true
    max="$(resolve_max "${1:-}")"; shift || true
    timeout="${1:-$DEFAULT_TIMEOUT}"
    deadline=$(( $(date +%s) + timeout ))
    rc=0
    while [[ ! -e "$output_file" ]]; do
        if (( $(date +%s) >= deadline )); then
            rc=1
            break
        fi
        sleep "$POLL_INTERVAL"
    done
    # Always release the slot — a timed-out agent must not permanently consume
    # admission capacity (that would deadlock the cap for the rest of the run).
    "$0" release "$output_dir" >/dev/null
    exit "$rc"
    ;;

  *)
    echo "flux-dispatch.sh: unknown command '$cmd'" >&2
    echo "Usage: flux-dispatch.sh <acquire|release|count|wait|reset> <output_dir> ..." >&2
    exit 2
    ;;
esac
