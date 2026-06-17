#!/usr/bin/env bats
# Behavioral tests for issue #6 — OUTPUT_DIR occupancy lock + UUID-in-filename.
#
# The fix lives as a prose contract in skills/flux-engine/phases/launch.md
# (instructions to the orchestrating LLM). These tests exercise the SHELL
# SEMANTICS that contract relies on, so a regression in the documented
# mechanism (e.g. a non-atomic lock, or a clobbering rename) is caught.

bats_require_minimum_version 1.5.0

setup() {
    TEST_DIR="$(mktemp -d)"
    OUTPUT_DIR="$TEST_DIR/out"
    mkdir -p "$OUTPUT_DIR"
}

teardown() {
    [[ -d "$TEST_DIR" ]] && rm -rf "$TEST_DIR"
}

# Reproduce the launch.md Step 2.0 lock-acquire snippet for a given UUID.
# Echoes the resolved OUTPUT_DIR (which may be auto-suffixed) on stdout.
_acquire_lock() {
    local base_dir="$1" uuid="$2" out="$1"
    local lock_dir="$out/.run-${uuid}.lock"
    mkdir "$lock_dir" 2>/dev/null || { echo "SELF_COLLISION"; return 1; }
    local other
    other=$(find "$base_dir" -maxdepth 1 -type d -name ".run-*.lock" \
            ! -name ".run-${uuid}.lock" 2>/dev/null)
    if [[ -n "$other" ]]; then
        rmdir "$lock_dir" 2>/dev/null || true
        out="${base_dir}-${uuid}"
        mkdir -p "$out"
        lock_dir="$out/.run-${uuid}.lock"
        mkdir "$lock_dir"
    fi
    echo "$out"
}

@test "first run acquires the lock on the shared OUTPUT_DIR" {
    run _acquire_lock "$OUTPUT_DIR" "uuid-aaaa"
    [[ "$status" -eq 0 ]]
    [[ "$output" == "$OUTPUT_DIR" ]]
    [[ -d "$OUTPUT_DIR/.run-uuid-aaaa.lock" ]]
}

@test "second concurrent run auto-suffixes to a disjoint directory" {
    # Run A holds the lock.
    _acquire_lock "$OUTPUT_DIR" "uuid-aaaa" >/dev/null
    # Run B on the same target must NOT reuse OUTPUT_DIR.
    run _acquire_lock "$OUTPUT_DIR" "uuid-bbbb"
    [[ "$status" -eq 0 ]]
    [[ "$output" == "${OUTPUT_DIR}-uuid-bbbb" ]]
    [[ -d "${OUTPUT_DIR}-uuid-bbbb/.run-uuid-bbbb.lock" ]]
    # Run A's lock is untouched.
    [[ -d "$OUTPUT_DIR/.run-uuid-aaaa.lock" ]]
}

@test "concurrent pre-clean does not wipe the other run's in-flight files" {
    # Run A holds the lock and has an in-flight UUID-named file.
    dir_a=$(_acquire_lock "$OUTPUT_DIR" "uuid-aaaa")
    touch "$dir_a/fd-safety.uuid-aaaa.md.partial"
    # Run B acquires (auto-suffixes) and runs ITS pre-clean in ITS own dir.
    dir_b=$(_acquire_lock "$OUTPUT_DIR" "uuid-bbbb")
    find "$dir_b" -maxdepth 1 -type f \
        \( -name "*.md" -o -name "*.md.partial" -o -name "peer-findings.jsonl" \) -delete
    # Run A's in-flight file survives.
    [[ -f "$dir_a/fd-safety.uuid-aaaa.md.partial" ]]
    [[ "$dir_a" != "$dir_b" ]]
}

@test "run-scoped glob selects only the current run's files" {
    # Two runs leave files in the SAME dir (e.g. --output-dir override without lock).
    touch "$OUTPUT_DIR/fd-safety.uuid-aaaa.md"
    touch "$OUTPUT_DIR/fd-safety.uuid-bbbb.md"
    touch "$OUTPUT_DIR/fd-quality.uuid-aaaa.md"
    shopt -s nullglob
    local matched=("$OUTPUT_DIR"/*.uuid-aaaa.md)
    shopt -u nullglob
    [[ "${#matched[@]}" -eq 2 ]]
    for f in "${matched[@]}"; do
        [[ "$f" == *uuid-aaaa.md ]]
    done
}

@test "agent name is recoverable from the UUID filename" {
    local f="$OUTPUT_DIR/fd-safety.uuid-aaaa.md"
    touch "$f"
    local name
    name=$(basename "$f" ".uuid-aaaa.md")
    [[ "$name" == "fd-safety" ]]
}

@test "mv -n refuses to clobber an existing terminal .md" {
    echo "run-A findings" > "$OUTPUT_DIR/fd-safety.uuid-aaaa.md"
    echo "run-B late write" > "$OUTPUT_DIR/fd-safety.uuid-aaaa.md.partial"
    # A late same-name rename must NOT overwrite the existing terminal file.
    run mv -n "$OUTPUT_DIR/fd-safety.uuid-aaaa.md.partial" "$OUTPUT_DIR/fd-safety.uuid-aaaa.md"
    [[ "$(cat "$OUTPUT_DIR/fd-safety.uuid-aaaa.md")" == "run-A findings" ]]
}
