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
            echo "$base"
            seen=$((seen + 1))
        fi
    done
    [[ "$EXPECTED" -gt 0 && "$seen" -ge "$EXPECTED" ]] && return 0 || return 1
}

# Check if all expected files are already present
if report_existing 2>/dev/null; then
    exit 0
fi

# Preferred: inotifywait (blocks until file events, near-zero CPU)
# Uses process substitution to avoid subshell/SIGPIPE issues with pipefail.
if command -v inotifywait >/dev/null 2>&1; then
    while IFS= read -r file; do
        [[ "$file" == *.md && "$file" != *.md.partial ]] || continue
        [[ "$file" == triage-table.md || "$file" == triage.md || "$file" == synthesis.md ]] && continue
        if [[ -z "${reported[$file]:-}" ]]; then
            reported[$file]=1
            echo "$file"
            seen=$((seen + 1))
            [[ "$EXPECTED" -gt 0 && "$seen" -ge "$EXPECTED" ]] && exit 0
        fi
    done < <(inotifywait -m -t "$TIMEOUT" -e close_write,moved_to --format '%f' "$OUTPUT_DIR" 2>/dev/null)
    # inotifywait exited (timeout or error) — check if we have everything
    report_existing 2>/dev/null && exit 0
    exit 1
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
