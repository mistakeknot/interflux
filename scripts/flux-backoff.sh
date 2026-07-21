#!/usr/bin/env bash
# flux-backoff.sh — transient-failure backpressure for agent dispatch (issue #9).
#
# Problem (finding C-2): launch.md cites ~30% retry-token waste at 16-agent
# fan-out, yet dispatch had no 429/backoff handling. The only retry was the
# synchronous partial-completion Retry Race Protocol, which retries at the SAME
# concurrency with NO backoff and cannot tell "rate-limited / never started"
# from "crashed" from "slow". A plain 429 leaves no .md/.partial and stays
# invisible until the 300s flux-watch timeout.
#
# This script adds a distinct TRANSIENT-FAILURE class with TCP/client-go style
# congestion control that composes with flux-dispatch.sh's flock slot semaphore:
#
#   * classify  — recognize 429 / rate-limit / overloaded as TRANSIENT, separate
#                 from terminal (Usage-Policy refusal) and unknown (crash/stall).
#   * delay     — exponential backoff + full jitter for a given attempt number,
#                 bounded by a cap. Prints the chosen delay (does not sleep).
#   * sleep     — compute the delay AND sleep it (delay + sleep in one call).
#   * decrease  — multiplicatively decrease the EFFECTIVE concurrency cap for the
#                 rest of the run (writes {OUTPUT_DIR}/.dispatch-cap). On sustained
#                 429 the cap halves each time, floored at MIN_EFFECTIVE_CAP.
#   * increase  — additive recovery (slow-start style) after a clean window.
#   * effective — print the current effective cap (min of base cap and the
#                 congestion-reduced cap). flux-dispatch.sh acquire reads this so
#                 the reduced cap actually throttles subsequent dispatches.
#   * reset     — clear the congestion cap back to the base.
#
# The effective-cap file is the shared state that lets backpressure compose with
# the existing semaphore: flux-dispatch.sh resolves max as
#   min(base_max, .dispatch-cap)  (see flux-dispatch.sh resolve_max).
# So a `decrease` here lowers the slot ceiling for every later `acquire`.
#
# Why BEFORE the 300s timeout: a 429 produces no .partial, so the stall/timeout
# path only notices it after the full window. The orchestrator must classify the
# subagent transcript as TRANSIENT the moment the Agent tool returns, then
# `decrease` + `sleep` + re-enqueue — engaging backpressure immediately.
#
# fd: this script does NOT take a flock fd of its own. The cap file is mutated
# under flux-dispatch.sh's existing fd-204 dispatch-slots lock so cap reads in
# `acquire` and cap writes here serialize against the same lock domain.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUDGET_CONFIG="${BUDGET_CONFIG:-${SCRIPT_DIR}/../config/flux-drive/budget.yaml}"

# Hybrid flock/mkdir locking (Sylveste-9cs) — see lib-lock.sh.
# shellcheck source=lib-lock.sh
source "$SCRIPT_DIR/lib-lock.sh"

# --- Tunables (env > budget.yaml > default) -------------------------------
# Backoff base/cap are in seconds. Jitter is "full jitter": the actual delay is
# a uniform random pick in [0, exp_delay], which decorrelates retries across the
# fan-out so a synchronized thundering-herd retry doesn't re-trigger the limit.
DEFAULT_BASE_DELAY=2        # seconds; attempt 1 caps exp window at base*2^0 = 2
DEFAULT_MAX_DELAY=60        # seconds; ceiling on the exponential window
DEFAULT_BACKOFF_FACTOR=2    # exponential multiplier
DEFAULT_DECREASE_FACTOR=2   # multiplicative DEcrease divisor (cap /= 2 per 429)
DEFAULT_MIN_EFFECTIVE_CAP=1 # never throttle below 1 in-flight (forward progress)

_budget_get() {
    # $1 = dotted key under `backoff:` in budget.yaml; echoes value or nothing.
    [[ -f "$BUDGET_CONFIG" ]] || return 0
    python3 - "$BUDGET_CONFIG" "$1" <<'PY' 2>/dev/null || true
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
node = (data.get("dispatch") or {}).get("backoff") or {}
val = node.get(sys.argv[2])
if isinstance(val, (int, float)) and val > 0:
    print(int(val) if float(val).is_integer() else val)
PY
}

_num() {
    # Resolve a numeric tunable: env override $1 → budget key $2 → default $3.
    local env_val="$1" budget_key="$2" default="$3" b
    if [[ -n "$env_val" && "$env_val" =~ ^[0-9]+$ && "$env_val" -gt 0 ]]; then
        echo "$env_val"; return 0
    fi
    b="$(_budget_get "$budget_key")"
    if [[ -n "$b" && "$b" =~ ^[0-9]+$ && "$b" -gt 0 ]]; then
        echo "$b"; return 0
    fi
    echo "$default"
}

BASE_DELAY="$(_num "${FLUX_BACKOFF_BASE_DELAY:-}" base_delay_secs "$DEFAULT_BASE_DELAY")"
MAX_DELAY="$(_num "${FLUX_BACKOFF_MAX_DELAY:-}" max_delay_secs "$DEFAULT_MAX_DELAY")"
BACKOFF_FACTOR="$(_num "${FLUX_BACKOFF_FACTOR:-}" factor "$DEFAULT_BACKOFF_FACTOR")"
DECREASE_FACTOR="$(_num "${FLUX_BACKOFF_DECREASE_FACTOR:-}" decrease_factor "$DEFAULT_DECREASE_FACTOR")"
MIN_EFFECTIVE_CAP="$(_num "${FLUX_BACKOFF_MIN_CAP:-}" min_effective_cap "$DEFAULT_MIN_EFFECTIVE_CAP")"

_cap_file()  { echo "${1%/}/.dispatch-cap"; }
_lock_file() { echo "${1%/}/.dispatch-slots.lock"; }  # shared fd-204 domain

# Read the congestion cap (the throttled ceiling). Empty/garbage = unset.
_read_cap() {
    local f="$1" v
    v="$(cat "$f" 2>/dev/null || true)"
    [[ "$v" =~ ^[0-9]+$ ]] && echo "$v" || echo ""
}

# --- classify: TRANSIENT vs TERMINAL vs UNKNOWN ---------------------------
# Reads candidate failure text from $1 (a file path) or, if $1 is "-" / absent,
# from stdin. Prints exactly one of: transient | terminal | unknown. Exit 0.
#
# TRANSIENT  — rate limited / overloaded / never started. Do NOT count as failed;
#              back off + re-enqueue + decrease concurrency.
# TERMINAL   — deterministic refusal (Usage Policy). Same input will refuse again;
#              caller must tier-downgrade, not plain-retry (handled in launch.md).
# UNKNOWN    — crash / silent stall / anything unrecognized. Falls through to the
#              existing Retry Race / stall-rescue path (no concurrency decrease).
classify() {
    local src="${1:--}" text
    if [[ "$src" == "-" ]]; then
        text="$(cat)"
    elif [[ -f "$src" ]]; then
        text="$(cat "$src")"
    else
        text="$src"   # treat a non-file argument as the literal text
    fi

    # Terminal first: the deterministic Usage-Policy refusal is NOT transient even
    # though it is a kind of API error. Anchor loosely (it can appear mid-line in a
    # transcript) but require the distinctive phrase.
    if grep -qiE 'unable to respond to this request.*violate (our|the) usage policy' <<<"$text"; then
        echo terminal; return 0
    fi

    # Transient: HTTP 429, named rate-limit / overloaded errors, quota/capacity.
    # Anthropic surfaces these as "429", "rate_limit_error", "overloaded_error",
    # "Overloaded", "Too Many Requests", "rate limit", "rate-limited".
    if grep -qiE '(^|[^0-9])429([^0-9]|$)|rate[ _-]?limit|overloaded|too many requests|quota exceeded|capacity|temporarily unavailable|service unavailable|(^|[^0-9])(502|503|529)([^0-9]|$)' <<<"$text"; then
        echo transient; return 0
    fi

    echo unknown
}

# --- delay: exponential backoff + full jitter (compute only) --------------
# Usage: delay <attempt>   (attempt is 1-based)
# exp_window = min(MAX_DELAY, BASE_DELAY * FACTOR^(attempt-1))
# delay      = uniform random in [0, exp_window]   (full jitter, AWS-style)
delay() {
    local attempt="${1:?delay requires <attempt>}"
    [[ "$attempt" =~ ^[0-9]+$ && "$attempt" -ge 1 ]] || attempt=1
    local window="$BASE_DELAY" i
    for (( i=1; i<attempt; i++ )); do
        window=$(( window * BACKOFF_FACTOR ))
        if (( window >= MAX_DELAY )); then window="$MAX_DELAY"; break; fi
    done
    (( window > MAX_DELAY )) && window="$MAX_DELAY"
    # Full jitter: pick uniformly in [0, window]. RANDOM is 0..32767.
    local d=$(( (RANDOM * (window + 1)) / 32768 ))
    (( d > window )) && d="$window"
    echo "$d"
}

# --- sleep: compute delay AND sleep it ------------------------------------
sleep_backoff() {
    local attempt="${1:?sleep requires <attempt>}"
    local d
    d="$(delay "$attempt")"
    sleep "$d"
    echo "$d"
}

# --- decrease: multiplicative concurrency decrease (congestion control) ----
# Usage: decrease <output_dir> [base_max]
# Halves the current effective cap (cap = ceil(cap / DECREASE_FACTOR)),
# floored at MIN_EFFECTIVE_CAP. If no cap is set yet, seeds from base_max
# (resolved via flux-dispatch.sh if absent) before halving. Mutates under the
# shared fd-204 dispatch lock so it is consistent with concurrent `acquire`s.
decrease() {
    local output_dir="${1:?decrease requires <output_dir>}"; shift || true
    local base_max="${1:-}"
    mkdir -p "$output_dir"
    local cap_file lock
    cap_file="$(_cap_file "$output_dir")"; lock="$(_lock_file "$output_dir")"

    if [[ -z "$base_max" ]]; then
        base_max="$(bash "$SCRIPT_DIR/flux-dispatch.sh" maxcap "$output_dir" 2>/dev/null || echo 6)"
    fi

    # Hold the shared dispatch lock for the read-modify-write; the critical
    # section echoes the new cap, captured through $() (lib-lock.sh contract).
    _with_lock_ex "$lock" _decrease_locked
}

# Runs under the fd-204 lock; sees decrease()'s locals via dynamic scoping.
_decrease_locked() {
    local cur new
    cur="$(_read_cap "$cap_file")"
    [[ -z "$cur" ]] && cur="$base_max"
    # ceil division so an odd cap doesn't collapse a step early
    new=$(( (cur + DECREASE_FACTOR - 1) / DECREASE_FACTOR ))
    (( new < MIN_EFFECTIVE_CAP )) && new="$MIN_EFFECTIVE_CAP"
    echo "$new" > "$cap_file"
    echo "$new"
}

# --- increase: additive recovery (slow-start) ------------------------------
# Usage: increase <output_dir> [base_max]
# Adds 1 to the effective cap after a clean window, never above base_max.
# Clears the cap file once it reaches base_max so resolution returns to normal.
increase() {
    local output_dir="${1:?increase requires <output_dir>}"; shift || true
    local base_max="${1:-}"
    mkdir -p "$output_dir"
    local cap_file lock
    cap_file="$(_cap_file "$output_dir")"; lock="$(_lock_file "$output_dir")"

    if [[ -z "$base_max" ]]; then
        base_max="$(bash "$SCRIPT_DIR/flux-dispatch.sh" maxcap "$output_dir" 2>/dev/null || echo 6)"
    fi

    _with_lock_ex "$lock" _increase_locked
}

# Runs under the fd-204 lock; sees increase()'s locals via dynamic scoping.
_increase_locked() {
    local cur n out
    cur="$(_read_cap "$cap_file")"
    if [[ -z "$cur" ]]; then
        out="$base_max"   # already at base; nothing throttled
    else
        n=$(( cur + 1 ))
        if (( n >= base_max )); then
            rm -f "$cap_file"   # fully recovered — resolution falls back to base
            out="$base_max"
        else
            echo "$n" > "$cap_file"
            out="$n"
        fi
    fi
    echo "$out"
}

# --- effective: print the current effective cap ---------------------------
# Usage: effective <output_dir> [base_max]
# Returns min(base_max, congestion_cap). flux-dispatch.sh calls this from
# resolve_max so a decreased cap throttles subsequent acquires.
effective() {
    local output_dir="${1:?effective requires <output_dir>}"; shift || true
    local base_max="${1:-6}"
    local cap_file cur
    cap_file="$(_cap_file "$output_dir")"
    cur="$(_read_cap "$cap_file")"
    if [[ -z "$cur" ]]; then
        echo "$base_max"; return 0
    fi
    if (( cur < base_max )); then echo "$cur"; else echo "$base_max"; fi
}

# --- reset: clear congestion cap back to base -----------------------------
reset() {
    local output_dir="${1:?reset requires <output_dir>}"
    local cap_file
    cap_file="$(_cap_file "$output_dir")"
    rm -f "$cap_file"
    echo "ok"
}

cmd="${1:?Usage: flux-backoff.sh <classify|delay|sleep|decrease|increase|effective|reset> ...}"
shift || true

case "$cmd" in
  classify) classify "${1:--}" ;;
  delay)    delay "${1:?delay requires <attempt>}" ;;
  sleep)    sleep_backoff "${1:?sleep requires <attempt>}" ;;
  decrease) decrease "$@" ;;
  increase) increase "$@" ;;
  effective) effective "$@" ;;
  reset)    reset "${1:?reset requires <output_dir>}" ;;
  *)
    echo "flux-backoff.sh: unknown command '$cmd'" >&2
    echo "Usage: flux-backoff.sh <classify|delay|sleep|decrease|increase|effective|reset> ..." >&2
    exit 2
    ;;
esac
