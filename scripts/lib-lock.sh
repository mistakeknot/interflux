#!/usr/bin/env bash
# lib-lock.sh — hybrid locking for the fd-204 dispatch-slots domain
# (Sylveste-9cs). Linux keeps the exact flock(1) subshell/fd semantics the
# scripts have always had; macOS ships no flock(1), so it falls back to a
# mkdir spin-lock with pid-based stale-lock stealing.
#
# Contract: the critical section runs in a SUBSHELL on both paths, so it
# communicates via files, stdout, and exit status only — never variables.
# Callers capture stdout with $() where they need a value back.
#
# Sourced by flux-dispatch.sh and flux-backoff.sh.

_LOCK_FALLBACK_TIMEOUT="${FLUX_LOCK_FALLBACK_TIMEOUT:-30}"  # mkdir path only

_have_flock() { command -v flock >/dev/null 2>&1; }

# _mkdir_lock_acquire <lockfile> <timeout_secs>
# Spin at 100ms until <lockfile>.d is created. A lock whose recorded holder
# pid is dead is stolen (crash mid-critical-section must not wedge forever —
# fd locks got that for free, mkdir locks need the pid check).
_mkdir_lock_acquire() {
    local lock_d="${1}.d" timeout="${2:-$_LOCK_FALLBACK_TIMEOUT}"
    local waited=0 max_ticks=$(( timeout * 10 )) holder
    while ! mkdir "$lock_d" 2>/dev/null; do
        holder="$(cat "${lock_d}/pid" 2>/dev/null || true)"
        if [[ -n "$holder" ]] && ! kill -0 "$holder" 2>/dev/null; then
            rm -rf "$lock_d" 2>/dev/null || true
            continue
        fi
        (( waited >= max_ticks )) && return 1
        sleep 0.1
        waited=$(( waited + 1 ))
    done
    echo "$$" > "${lock_d}/pid" 2>/dev/null || true
    return 0
}

_mkdir_lock_release() { rm -rf "${1}.d" 2>/dev/null || true; }

# _with_lock_ex <lockfile> <cmd> [args...] — run <cmd> under an exclusive
# lock. Returns <cmd>'s exit status; 99 = fallback lock acquisition timeout.
_with_lock_ex() {
    local lock="$1"; shift
    if _have_flock; then
        ( flock -x 204; "$@" ) 204>"$lock"
    else
        _mkdir_lock_acquire "$lock" "$_LOCK_FALLBACK_TIMEOUT" || return 99
        local rc=0
        ( "$@" ) || rc=$?
        _mkdir_lock_release "$lock"
        return $rc
    fi
}

# _with_lock_sh <lockfile> <cmd> [args...] — shared (reader) lock. The mkdir
# fallback has no shared mode, so readers briefly take the exclusive lock.
_with_lock_sh() {
    local lock="$1"; shift
    if _have_flock; then
        ( flock -s 204; "$@" ) 204>"$lock"
    else
        _with_lock_ex "$lock" "$@"
    fi
}
