#!/usr/bin/env bash
# test_teams_detect.sh — unit tests for teams_detect.sh.
#
# Stubs `claude --version` via a temp PATH directory. Asserts (stdout, exit) per case.
# Run: bash interverse/interflux/tests/test_teams_detect.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DETECT="$PLUGIN_DIR/scripts/teams_detect.sh"
BASH_BIN="$(command -v bash)"

if [[ ! -x "$DETECT" ]]; then
    echo "FAIL setup: $DETECT not executable" >&2
    exit 1
fi

stub_dir=$(mktemp -d)
trap 'rm -rf "$stub_dir"' EXIT

# Stub helper: $1 = claude --version output
make_stub() {
    cat > "$stub_dir/claude" <<EOF
#!/usr/bin/env bash
if [[ "\${1:-}" == "--version" ]]; then
    echo "$1"
    exit 0
fi
exit 1
EOF
    chmod +x "$stub_dir/claude"
}

passed=0
failed=0

assert_case() {
    local name="$1" expected_stdout="$2" expected_exit="$3"
    shift 3
    local actual_stdout actual_exit
    actual_stdout=$("$@" 2>/dev/null) || true
    actual_exit=$("$@" >/dev/null 2>&1; echo $?)
    if [[ "$actual_stdout" == "$expected_stdout" && "$actual_exit" == "$expected_exit" ]]; then
        echo "PASS  $name"
        ((passed++))
    else
        echo "FAIL  $name"
        echo "      expected: stdout=[$expected_stdout] exit=$expected_exit"
        echo "      actual:   stdout=[$actual_stdout] exit=$actual_exit"
        ((failed++))
    fi
}

# Case 1: env disabled (CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS unset/0)
make_stub "2.1.40 (Claude Code)"
assert_case "env-disabled" "disabled" "1" \
    env -u CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS PATH="$stub_dir:$PATH" bash "$DETECT"

# Case 2: env=0 explicit
assert_case "env-zero" "disabled" "1" \
    env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=0 PATH="$stub_dir:$PATH" bash "$DETECT"

# Case 3: claude version too old (2.1.31 < 2.1.32)
make_stub "2.1.31 (Claude Code)"
assert_case "version-too-old" "version_too_old" "1" \
    env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 PATH="$stub_dir:$PATH" bash "$DETECT"

# Case 4: claude version exactly minimum
make_stub "2.1.32 (Claude Code)"
assert_case "version-exact-min" "available" "0" \
    env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 PATH="$stub_dir:$PATH" bash "$DETECT"

# Case 5: claude version above minimum
make_stub "2.1.40 (Claude Code)"
assert_case "version-above-min" "available" "0" \
    env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 PATH="$stub_dir:$PATH" bash "$DETECT"

# Case 6: claude version with build suffix (sort -V handles after normalize)
make_stub "2.1.32+build.5 (Claude Code)"
assert_case "version-build-suffix" "available" "0" \
    env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 PATH="$stub_dir:$PATH" bash "$DETECT"

# Case 7: claude version with hyphen pre-release
make_stub "2.1.40-beta1 (Claude Code)"
assert_case "version-prerelease-suffix" "available" "0" \
    env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 PATH="$stub_dir:$PATH" bash "$DETECT"

# Case 8: garbage version output
make_stub "garbage-no-version-here"
assert_case "version-garbage" "version_unparseable" "1" \
    env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 PATH="$stub_dir:$PATH" bash "$DETECT"

# Case 9: claude not on PATH (uses an empty stub dir, no claude binary)
empty_dir=$(mktemp -d)
trap 'rm -rf "$stub_dir" "$empty_dir"' EXIT
assert_case "no-claude-on-path" "version_unparseable" "1" \
    env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 PATH="$empty_dir" "$BASH_BIN" "$DETECT"

# Case 10: future major version (3.0.0 > 2.1.32)
make_stub "3.0.0 (Claude Code)"
assert_case "version-major-bump" "available" "0" \
    env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 PATH="$stub_dir:$PATH" bash "$DETECT"

echo
echo "Results: $passed passed, $failed failed"
exit $((failed > 0 ? 1 : 0))
