#!/usr/bin/env bash
# Install interflux git hooks (Sylveste-10p).
#
# Points core.hooksPath at the tracked .githooks/ directory so the
# routing frontmatter drift gate (.githooks/pre-commit) runs on every
# commit. interflux ships no other git hooks, so taking over hooksPath
# is safe here.
#
# Re-run after cloning or whenever .githooks/ changes. Idempotent.
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

if [ ! -d .githooks ]; then
  echo "Missing .githooks directory; nothing to install." >&2
  exit 1
fi

if [ -f .githooks/pre-commit ]; then
  chmod +x .githooks/pre-commit
fi

git config core.hooksPath .githooks

echo "Installed interflux git hooks (core.hooksPath=.githooks)."
echo "Bypass a single commit with: git commit --no-verify"
