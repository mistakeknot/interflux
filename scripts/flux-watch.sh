#!/usr/bin/env bash
# flux-watch.sh — Watch OUTPUT_DIR for agent .md file completions.
# Prefers inotifywait (zero-CPU filesystem events), falls back to 5s polling.
#
# Usage: flux-watch.sh <output_dir> [expected_count] [timeout_secs]
# Output: prints each completed .md filename to stdout as it appears
# Exit: 0 = all expected files seen, 1 = timeout (some missing)
#
# Stall rescue (opt-in):
#   STALL_RESCUE=1            — enable stall detection (default off)
#   STALL_TIMEOUT=60          — seconds without progress before rescue (default 60s)
#   EXPECTED_AGENTS="a\nb\nc" — newline-separated names; required for rescue
# When a stall is detected for an expected agent that has neither .md nor .partial,
# write an error stub `{agent}.md` so synthesis sees the stall as data, not silence.
set -euo pipefail

OUTPUT_DIR="${1:?Usage: flux-watch.sh <output_dir> [expected_count] [timeout_secs]}"
EXPECTED="${2:-0}"
TIMEOUT="${3:-300}"

STALL_RESCUE="${STALL_RESCUE:-0}"
STALL_TIMEOUT="${STALL_TIMEOUT:-60}"
EXPECTED_AGENTS="${EXPECTED_AGENTS:-}"

seen=0
declare -A reported  # track already-reported files
START_TIME=$(date +%s)

# Format elapsed time
elapsed_str() {
    local now elapsed
    now=$(date +%s)
    elapsed=$((now - START_TIME))
    if [[ "$elapsed" -lt 60 ]]; then
        echo "${elapsed}s"
    else
        echo "$((elapsed / 60))m$((elapsed % 60))s"
    fi
}

# Report a completed agent with progress
report_agent() {
    local base="$1"
    local agent_name="${base%.md}"
    if [[ "$EXPECTED" -gt 0 ]]; then
        echo "[${seen}/${EXPECTED} | $(elapsed_str)] ${agent_name}"
    else
        echo "[${seen} | $(elapsed_str)] ${agent_name}"
    fi
}

# Report files that already exist (agents that completed before we started watching)
report_existing() {
    for f in "$OUTPUT_DIR"/*.md; do
        [[ -e "$f" ]] || continue
        local base
        base=$(basename "$f")
        [[ "$base" == *.partial ]] && continue
        [[ "$base" == triage-table.md ]] && continue
        [[ "$base" == triage.md ]] && continue
        [[ "$base" == synthesis.md ]] && continue
        if [[ -z "${reported[$base]:-}" ]]; then
            reported[$base]=1
            seen=$((seen + 1))
            report_agent "$base"
        fi
    done
    [[ "$EXPECTED" -gt 0 && "$seen" -ge "$EXPECTED" ]] && return 0 || return 1
}

# Write a stall error stub for an agent. Pre-marks reported[] so the close_write
# event we just generated does not double-count toward seen.
write_stall_stub() {
    local agent="$1"
    local stub="$OUTPUT_DIR/${agent}.md"
    [[ -e "$stub" ]] && return 0  # someone wrote it; don't clobber

    local base="${agent}.md"
    reported[$base]=1
    seen=$((seen + 1))

    cat > "$stub" <<EOF
# ${agent} — stall rescue

**Status: stalled** (no output for ${STALL_TIMEOUT}s; flux-watch wrote this stub)

The agent dispatched but produced no .partial or .md within the stall window.
Synthesis should treat this as a non-finding (zero issues) and note the stall.

--- VERDICT ---
STATUS: error
FILES: 0
FINDINGS: 0
SUMMARY: Agent stalled — no output within ${STALL_TIMEOUT}s of stall window. Likely permission error, transport failure, or silent refusal.
---
EOF

    # Append peer finding so synthesis sees the stall as data
    if [[ -n "${OUTPUT_DIR}" ]] && [[ -d "$OUTPUT_DIR" ]]; then
        local pf="$OUTPUT_DIR/peer-findings.jsonl"
        local ts
        ts=$(date -Iseconds)
        printf '{"ts":"%s","agent":"%s","kind":"stall","severity":"warn","message":"Agent stalled — no output within %ss; rescued by flux-watch"}\n' \
            "$ts" "$agent" "$STALL_TIMEOUT" >> "$pf"
    fi

    report_agent "${agent}.md"
}

# Walk EXPECTED_AGENTS list, write stall stubs for any with neither .md nor .partial
# (and not already reported). Always returns 0 so `set -e` callers don't propagate
# the rescue count as a failure.
rescue_stalled() {
    [[ "$STALL_RESCUE" != "1" ]] && return 0
    [[ -z "$EXPECTED_AGENTS" ]] && return 0

    local agent
    while IFS= read -r agent; do
        [[ -z "$agent" ]] && continue
        local base="${agent}.md"
        # Skip if already reported (terminal) or in-progress (.partial exists)
        [[ -n "${reported[$base]:-}" ]] && continue
        [[ -e "$OUTPUT_DIR/${agent}.md" ]] && continue
        [[ -e "$OUTPUT_DIR/${agent}.md.partial" ]] && continue
        # No .md, no .partial, not reported — stalled
        write_stall_stub "$agent"
    done <<< "$EXPECTED_AGENTS"
    return 0
}

# Preferred: inotifywait (blocks until file events, near-zero CPU)
# Start inotifywait BEFORE scanning existing files to close the race window:
# any agent completing between scan and watch would otherwise be missed.
if command -v inotifywait >/dev/null 2>&1; then
    # Start watcher first — events queue in its buffer while we scan
    exec 3< <(inotifywait -m -t "$TIMEOUT" -e close_write,moved_to --format '%f' "$OUTPUT_DIR" 2>/dev/null)
    # $! after exec 3< <(...) captures the process-substitution subshell PID, not the
    # inotifywait child. Killing that PID no-ops and leaves inotifywait running —
    # orphaned watchers exhaust /proc/sys/fs/inotify/max_user_watches over time.
    # Resolve the real child via pgrep to ensure kill targets the right process.
    INOTIFY_PID=$(pgrep -P $$ inotifywait | head -1)
    [[ -z "$INOTIFY_PID" ]] && INOTIFY_PID=$!

    # Now scan for files that already completed before the watcher started
    if report_existing 2>/dev/null; then
        kill "$INOTIFY_PID" 2>/dev/null || true
        exec 3<&-
        exit 0
    fi

    # Read events from the already-running watcher.
    # When STALL_RESCUE=1, bound read with -t STALL_TIMEOUT so we wake periodically
    # to check for stalled agents. Otherwise, plain blocking read (back-compat).
    while true; do
        if [[ "$STALL_RESCUE" == "1" ]]; then
            # Bounded read: timeout returns exit 142 (>128); rescue, then retry
            if IFS= read -r -t "$STALL_TIMEOUT" file <&3; then
                :  # got a file event; process below
            else
                # Read timed out (no event for STALL_TIMEOUT seconds) OR EOF
                # If inotifywait is still alive, this is a stall window — rescue.
                if kill -0 "$INOTIFY_PID" 2>/dev/null; then
                    rescue_stalled
                    if [[ "$EXPECTED" -gt 0 && "$seen" -ge "$EXPECTED" ]]; then
                        kill "$INOTIFY_PID" 2>/dev/null || true
                        exec 3<&-
                        exit 0
                    fi
                    continue
                else
                    break  # inotifywait exited (overall TIMEOUT); fall through
                fi
            fi
        else
            IFS= read -r file <&3 || break
        fi

        [[ "$file" == *.md && "$file" != *.md.partial ]] || continue
        # Aborted-original partials (BP-C2 retry race protocol) are
        # terminal-but-not-success; they don't count toward seen.
        [[ "$file" == *.md.partial.aborted-* || "$file" == *.abort ]] && continue
        [[ "$file" == triage-table.md || "$file" == triage.md || "$file" == synthesis.md ]] && continue
        if [[ -z "${reported[$file]:-}" ]]; then
            reported[$file]=1
            seen=$((seen + 1))
            report_agent "$file"
            if [[ "$EXPECTED" -gt 0 && "$seen" -ge "$EXPECTED" ]]; then
                kill "$INOTIFY_PID" 2>/dev/null || true
                exec 3<&-
                exit 0
            fi
        fi
    done
    exec 3<&-
    # inotifywait exited (timeout or error) — rescue any remaining stalls, then check
    rescue_stalled
    report_existing 2>/dev/null && exit 0
    exit 1
fi

# Check if all expected files are already present (no inotifywait available)
if report_existing 2>/dev/null; then
    exit 0
fi

# Fallback: 5s polling loop. Stall checks happen at STALL_TIMEOUT-aligned ticks
# (5s granularity floor — i.e., we only rescue at multiples of 5s within STALL_TIMEOUT).
elapsed=0
last_stall_check=0
while [[ "$elapsed" -lt "$TIMEOUT" ]]; do
    if report_existing 2>/dev/null; then
        exit 0
    fi
    if [[ "$STALL_RESCUE" == "1" ]] && (( elapsed - last_stall_check >= STALL_TIMEOUT )); then
        rescue_stalled
        last_stall_check=$elapsed
        if [[ "$EXPECTED" -gt 0 && "$seen" -ge "$EXPECTED" ]]; then
            exit 0
        fi
    fi
    sleep 5
    elapsed=$((elapsed + 5))
done

# Final check — rescue any still-missing then succeed/fail
rescue_stalled
report_existing 2>/dev/null && exit 0
exit 1
