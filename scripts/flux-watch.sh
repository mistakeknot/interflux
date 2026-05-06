#!/usr/bin/env bash
# flux-watch.sh — Watch OUTPUT_DIR for agent .md file completions.
# Prefers inotifywait (zero-CPU filesystem events), falls back to 5s polling.
#
# Usage: flux-watch.sh <output_dir> [expected_count] [timeout_secs]
# Output: prints each completed .md filename to stdout as it appears
# Exit: 0 = all expected files seen, 1 = timeout (some missing)
set -euo pipefail

OUTPUT_DIR="${1:?Usage: flux-watch.sh <output_dir> [expected_count] [timeout_secs]}"
EXPECTED="${2:-0}"
TIMEOUT="${3:-300}"

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

    # Read events from the already-running watcher
    while IFS= read -r file <&3; do
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
    # inotifywait exited (timeout or error) — check if we have everything
    report_existing 2>/dev/null && exit 0
    exit 1
fi

# Check if all expected files are already present (no inotifywait available)
if report_existing 2>/dev/null; then
    exit 0
fi

# Fallback: 5s polling loop
elapsed=0
while [[ "$elapsed" -lt "$TIMEOUT" ]]; do
    if report_existing 2>/dev/null; then
        exit 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
done

# Final check
report_existing 2>/dev/null && exit 0
exit 1
