#!/usr/bin/env bash
# interflux session-start hook — source interbase and emit status
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source interbase (live or stub)
source "$HOOK_DIR/interbase-stub.sh"

# Emit ecosystem status (no-op in stub mode)
ib_session_status
