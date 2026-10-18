#!/usr/bin/env bats
# Tests for launch-exa.sh key resolution: unset, the unexpanded plugin.json
# placeholder, and the secrets-file fallback. A stub exa-mcp-server reports
# only whether it received the expected key, so the test never prints it.

bats_require_minimum_version 1.5.0

setup() {
    LAUNCH="$BATS_TEST_DIRNAME/../scripts/launch-exa.sh"
    WORK="$(mktemp -d)"
    mkdir -p "$WORK/bin" "$WORK/home" "$WORK/secrets"
    cat >"$WORK/bin/exa-mcp-server" <<'STUB'
#!/usr/bin/env bash
if [[ "${EXA_API_KEY:-}" == "file-key-123" ]]; then echo "stub: file key received"
elif [[ "${EXA_API_KEY:-}" == "env-key-456" ]]; then echo "stub: env key received"
else echo "stub: wrong key"; fi
STUB
    chmod +x "$WORK/bin/exa-mcp-server"
    export HOME="$WORK/home" SECRETS_DIR="$WORK/secrets"
    export PATH="$WORK/bin:$PATH"
}

teardown() {
    [[ -d "$WORK" ]] && rm -rf "$WORK"
}

@test "unset key and no file: exits 78" {
    run env -u EXA_API_KEY "$LAUNCH"
    [[ "$status" -eq 78 ]]
}

@test "placeholder key and no file: exits 78" {
    run env 'EXA_API_KEY=${EXA_API_KEY}' "$LAUNCH"
    [[ "$status" -eq 78 ]]
}

@test "placeholder key with readable file: uses the file key" {
    printf 'file-key-123\n' >"$SECRETS_DIR/EXA_API_KEY"
    run env 'EXA_API_KEY=${EXA_API_KEY}' "$LAUNCH"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"file key received"* ]]
    [[ "$output" != *"file-key-123"* ]]
}

@test "unset key with readable file: uses the file key" {
    printf 'file-key-123\n' >"$SECRETS_DIR/EXA_API_KEY"
    run env -u EXA_API_KEY "$LAUNCH"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"file key received"* ]]
}

@test "real env key wins over the file" {
    printf 'file-key-123\n' >"$SECRETS_DIR/EXA_API_KEY"
    run env EXA_API_KEY=env-key-456 "$LAUNCH"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"env key received"* ]]
}

@test "empty file: exits 78" {
    : >"$SECRETS_DIR/EXA_API_KEY"
    run env -u EXA_API_KEY "$LAUNCH"
    [[ "$status" -eq 78 ]]
}
