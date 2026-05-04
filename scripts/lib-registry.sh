#!/usr/bin/env bash
# lib-registry.sh — atomic mutate helpers for model-registry.yaml
#
# Source this file from scripts that mutate config/flux-drive/model-registry.yaml.
# Replaces the copy-pasted flock→cp→python3-heredoc→validate→mv pattern with one
# vetted implementation. Pairs with scripts/lib_registry.py.
#
# Usage:
#   source "${CLAUDE_PLUGIN_ROOT}/scripts/lib-registry.sh"
#   registry_atomic_mutate "$MODEL_REGISTRY" set-field <slug> <key> <value-json>
#   registry_atomic_mutate "$MODEL_REGISTRY" promote   <slug>
#
# Returns:
#   0  success
#   1  mutation failed (unspecified)
#   2  registry parse error or registry path missing
#   3  slug not found OR lock timeout (caller distinguishes via stderr)
#   4  invalid invocation
#
# Lock fd is hardcoded to 201 to match existing fluxbench scripts. If a caller
# needs a different fd domain, they should source lib-registry.sh in a subshell
# or use a different lock primitive.

set -euo pipefail

_LIB_REGISTRY_PY="${_LIB_REGISTRY_PY:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}/scripts/lib_registry.py}"

registry_atomic_mutate() {
  local registry="$1"
  shift
  local op="$1"
  shift  # remaining args are op-specific

  if [[ ! -f "$registry" ]]; then
    echo "lib-registry: registry not found: $registry" >&2
    return 2
  fi

  local lock_path="${registry}.lock"
  local _flock_rc=0

  # Subshell uses EXIT trap (not RETURN — RETURN doesn't fire on SIGINT or
  # set -e exits). On any non-zero exit from inside, the mv is skipped, so the
  # live registry stays clean.
  (
    flock -w 30 -x 201 || exit 3
    _tmp_reg=$(mktemp)
    trap 'rm -f "$_tmp_reg"' EXIT

    cp "$registry" "$_tmp_reg"

    # Run the mutation against the tmp file. lib_registry.py exit codes:
    # 0 ok, 2 parse error, 3 slug not found, 4 bad invocation.
    python3 "$_LIB_REGISTRY_PY" "$op" "$_tmp_reg" "$@" || exit $?

    # Atomic swap: mv is atomic on the same filesystem (POSIX rename).
    mv "$_tmp_reg" "$registry"
  ) 201>"$lock_path" || _flock_rc=$?

  case "$_flock_rc" in
    0) return 0 ;;
    2) echo "lib-registry: parse error in $registry" >&2; return 2 ;;
    3) return 3 ;;
    4) echo "lib-registry: invalid invocation" >&2; return 4 ;;
    *)
      echo "lib-registry: mutate failed for $registry (rc=$_flock_rc)" >&2
      return 1
      ;;
  esac
}

# Convenience wrapper: set a single string field on a model.
registry_set_string_field() {
  local registry="$1" slug="$2" key="$3" value="$4"
  # Encode as JSON string
  local json_value
  json_value=$(printf '%s' "$value" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
  registry_atomic_mutate "$registry" set-field "$slug" "$key" "$json_value"
}

# Convenience wrapper: validate a registry file is parseable (no mutation, no lock).
registry_validate() {
  local registry="$1"
  python3 "$_LIB_REGISTRY_PY" validate "$registry"
}
