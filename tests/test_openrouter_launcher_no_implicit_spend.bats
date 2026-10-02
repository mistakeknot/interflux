#!/usr/bin/env bats
# openrouter-dispatch bills per token; the launcher must not start it by default.

setup() {
  LAUNCHER="$(cd "$BATS_TEST_DIRNAME/../scripts" && pwd)/launch-openrouter.sh"
  BIN="$(mktemp -d)"
  # A fake node that records being started, so a pass means the launcher stopped first.
  printf '#!/bin/sh\necho NODE-STARTED\n' > "$BIN/node"; chmod +x "$BIN/node"
  export PATH="$BIN:$PATH"
}
teardown() { rm -rf "$BIN"; }

start() { env -i PATH="$PATH" HOME="$HOME" "$@" bash "$LAUNCHER"; }

@test "a real key alone does not start the server" {
  run start OPENROUTER_API_KEY=sk-or-real OPENROUTER_SPEND_CEILING_USD=1.00
  [ "$status" -eq 0 ]; [[ "$output" != *NODE-STARTED* ]]; [[ "$output" == *ALLOW_PAID_DISPATCH* ]]
}
@test "an unexpanded placeholder key is rejected even with opt-in" {
  run start OPENROUTER_API_KEY='${OPENROUTER_API_KEY}' OPENROUTER_ALLOW_PAID_DISPATCH=1 OPENROUTER_SPEND_CEILING_USD=1.00
  [[ "$output" != *NODE-STARTED* ]]; [[ "$output" == *placeholder* ]]
}
@test "no spend ceiling is rejected even with opt-in" {
  run start OPENROUTER_API_KEY=sk-or-real OPENROUTER_ALLOW_PAID_DISPATCH=1
  [[ "$output" != *NODE-STARTED* ]]; [[ "$output" == *CEILING* ]]
}
@test "zero ceiling is rejected" {
  run start OPENROUTER_API_KEY=sk-or-real OPENROUTER_ALLOW_PAID_DISPATCH=1 OPENROUTER_SPEND_CEILING_USD=0
  [[ "$output" != *NODE-STARTED* ]]
}
@test "no key still does not start" {
  run start OPENROUTER_ALLOW_PAID_DISPATCH=1 OPENROUTER_SPEND_CEILING_USD=1.00
  [[ "$output" != *NODE-STARTED* ]]
}
@test "key, opt-in and ceiling together start it" {
  mkdir -p "$BATS_TEST_DIRNAME/../mcp-servers/openrouter-dispatch/dist"
  created=0; [ -f "$BATS_TEST_DIRNAME/../mcp-servers/openrouter-dispatch/dist/index.js" ] || { touch "$BATS_TEST_DIRNAME/../mcp-servers/openrouter-dispatch/dist/index.js"; created=1; }
  run start OPENROUTER_API_KEY=sk-or-real OPENROUTER_ALLOW_PAID_DISPATCH=1 OPENROUTER_SPEND_CEILING_USD=1.00
  [ "$created" = 1 ] && rm -f "$BATS_TEST_DIRNAME/../mcp-servers/openrouter-dispatch/dist/index.js"
  [[ "$output" == *NODE-STARTED* ]]
}
