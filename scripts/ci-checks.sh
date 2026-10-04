#!/usr/bin/env bash
# Independent CI recipe for the existing required routing-drift audit.
# Python and PyYAML are supplied by the registry-pinned Ubuntu 24.04 image.
set -euo pipefail
[[ "${CI:-}" == true && -n "${CI_SOURCE_SHA:-}" ]] || {
  echo "fresh CI clone and CI_SOURCE_SHA required" >&2; exit 2;
}
[[ -d .git && "$(git rev-parse HEAD)" == "$CI_SOURCE_SHA" ]] || {
  echo "source checkout does not match admitted commit" >&2; exit 2;
}
python3 --version
python3 -c 'import yaml; print("PyYAML " + yaml.__version__)'
python3 scripts/verify_frontmatter.py --strict --root . --agent-dir agents
