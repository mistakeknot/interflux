#!/usr/bin/env bash
# Claude Code treats exit 2 as a blocking PreToolUse error. Keep unrelated
# writes usable if Python is absent; fail closed for a melange target.
hook_input=
IFS= read -r -d '' hook_input || :
if ! command -v python3 >/dev/null 2>&1; then
  case "$hook_input" in
    *docs/research/flux-melange*) exit 2 ;;
    *) exit 0 ;;
  esac
fi
hook_dir=${BASH_SOURCE[0]%/*}
printf '%s' "$hook_input" | python3 "$hook_dir/redact-melange-write.py" || exit 2
