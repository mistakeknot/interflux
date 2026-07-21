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
#       (Re)initialize the slot file to zero in-flight and clear any congestion
#       cap from a prior run. Call once before a wave.
#   flux-dispatch.sh maxcap <output_dir> [max]
#       Print the resolved BASE cap (ignoring the congestion cap). Used by
#       scripts/flux-backoff.sh to seed the multiplicative-decrease cap.
#
# Backpressure (issue #9): scripts/flux-backoff.sh writes a congestion cap to
# {OUTPUT_DIR}/.dispatch-cap on sustained 429s. `acquire` claims against the
# EFFECTIVE cap = min(base_max, .dispatch-cap), so transient-failure backpressure
# multiplicatively lowers the live slot ceiling. See flux-backoff.sh.
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

# Hybrid flock/mkdir locking (Sylveste-9cs) — see lib-lock.sh.
# shellcheck source=lib-lock.sh
source "$SCRIPT_DIR/lib-lock.sh"

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
_cap_file()  { echo "${1%/}/.dispatch-cap"; }   # congestion cap (issue #9 backpressure)

# Effective cap = min(base_max, congestion_cap). The congestion cap is written by
# flux-backoff.sh `decrease` on sustained 429s (issue #9), so a transient-failure
# backpressure event lowers the slot ceiling for every subsequent acquire. When no
# congestion cap is set, the effective cap equals the base resolved cap.
effective_max() {
    local output_dir="$1" base="$2" cap_file cur
    cap_file="$(_cap_file "$output_dir")"
    cur="$(cat "$cap_file" 2>/dev/null || true)"
    if [[ "$cur" =~ ^[0-9]+$ ]] && (( cur > 0 )) && (( cur < base )); then
        echo "$cur"
    else
        echo "$base"
    fi
}

# Read the current count (0 if file missing/empty/garbage).
_read_count() {
    local f="$1" v
    v="$(cat "$f" 2>/dev/null || true)"
    [[ "$v" =~ ^[0-9]+$ ]] && echo "$v" || echo 0
}

# --- fd-204 critical sections (run via _with_lock_ex/_with_lock_sh) --------
# These read the globals set in the case arms below ($slot, $cap,
# $output_dir, $base_max). They execute in a subshell on both lock paths, so
# they communicate via files, stdout, and exit status only.
_reset_locked() {
    echo 0 > "$slot"
    rm -f "$cap"   # clear any congestion cap left by a prior run (issue #9)
}
_acquire_locked() {
    local eff_local cur
    eff_local="$(effective_max "$output_dir" "$base_max")"
    cur="$(_read_count "$slot")"
    if (( cur < eff_local )); then
        echo $(( cur + 1 )) > "$slot"
        return 0   # claimed
    fi
    return 10      # full
}
_release_locked() {
    local cur
    cur="$(_read_count "$slot")"
    if (( cur > 0 )); then
        echo $(( cur - 1 )) > "$slot"
    else
        echo 0 > "$slot"
    fi
}

cmd="${1:?Usage: flux-dispatch.sh <acquire|release|count|wait|reset> <output_dir> ...}"
shift || true

case "$cmd" in
  reset)
    output_dir="${1:?reset requires <output_dir>}"; shift || true
    mkdir -p "$output_dir"
    slot="$(_slot_file "$output_dir")"; lock="$(_lock_file "$output_dir")"; cap="$(_cap_file "$output_dir")"
    _with_lock_ex "$lock" _reset_locked
    echo "ok 0/$(resolve_max "${1:-}")"
    ;;

  count)
    output_dir="${1:?count requires <output_dir>}"
    slot="$(_slot_file "$output_dir")"; lock="$(_lock_file "$output_dir")"
    mkdir -p "$output_dir"
    _with_lock_sh "$lock" _read_count "$slot"
    ;;

  acquire)
    output_dir="${1:?acquire requires <output_dir>}"; shift || true
    base_max="$(resolve_max "${1:-}")"; shift || true
    timeout="${1:-$DEFAULT_TIMEOUT}"
    mkdir -p "$output_dir"
    slot="$(_slot_file "$output_dir")"; lock="$(_lock_file "$output_dir")"
    deadline=$(( $(date +%s) + timeout ))
    while :; do
        claimed=""
        eff=""
        # Critical section: re-read the effective (congestion-adjusted) cap and
        # claim a slot if one is free. Re-reading inside the loop means a mid-run
        # flux-backoff.sh `decrease` (issue #9) throttles pending acquires too.
        _with_lock_ex "$lock" _acquire_locked && claimed=1 || claimed=""
        eff="$(effective_max "$output_dir" "$base_max")"
        if [[ -n "$claimed" ]]; then
            echo "ok $(_read_count "$slot")/$eff"
            exit 0
        fi
        if (( $(date +%s) >= deadline )); then
            echo "timeout $(_read_count "$slot")/$eff" >&2
            exit 1
        fi
        sleep "$POLL_INTERVAL"
    done
    ;;

  maxcap)
    # Print the resolved BASE cap (ignores the congestion cap). flux-backoff.sh
    # `decrease`/`increase` call this to seed the congestion cap from the base.
    output_dir="${1:?maxcap requires <output_dir>}"; shift || true
    resolve_max "${1:-}"
    ;;

  release)
    output_dir="${1:?release requires <output_dir>}"
    slot="$(_slot_file "$output_dir")"; lock="$(_lock_file "$output_dir")"
    mkdir -p "$output_dir"
    _with_lock_ex "$lock" _release_locked
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
