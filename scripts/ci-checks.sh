#!/usr/bin/env bash
# Independent CI recipe for the required checks: the routing-drift audit and the pytest suite.
# Python, PyYAML and pytest come from the registry-pinned Ubuntu 24.04 image. gitleaks is not in
# the image, so this recipe downloads the one version the tests expect and verifies it against the
# upstream release checksum before installing it where the tests look (~/.local/bin).
set -euo pipefail
[[ "${CI:-}" == true && -n "${CI_SOURCE_SHA:-}" ]] || { echo "fresh CI clone and CI_SOURCE_SHA required" >&2; exit 2; }
[[ -d .git && "$(git rev-parse HEAD)" == "$CI_SOURCE_SHA" ]] || { echo "source checkout does not match admitted commit" >&2; exit 2; }

GITLEAKS_VERSION=8.30.1
# sha256 of gitleaks_8.30.1_linux_x64.tar.gz from the upstream gitleaks_8.30.1_checksums.txt.
GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
GITLEAKS_URL="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"

python3 --version
python3 -c 'import yaml; print("PyYAML " + yaml.__version__)'
python3 -m pytest --version

echo "== audit =="
python3 scripts/verify_frontmatter.py --strict --root . --agent-dir agents

echo "== gitleaks ${GITLEAKS_VERSION} =="
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
curl --fail --silent --show-error --location --retry 3 --output "$work/gitleaks.tar.gz" "$GITLEAKS_URL"
echo "${GITLEAKS_SHA256}  ${work}/gitleaks.tar.gz" | sha256sum --check --strict -
tar -xzf "$work/gitleaks.tar.gz" -C "$work" gitleaks
mkdir -p "$HOME/.local/bin"
install -m 0755 "$work/gitleaks" "$HOME/.local/bin/gitleaks"
[[ "$("$HOME/.local/bin/gitleaks" version)" == "$GITLEAKS_VERSION" ]] || { echo "gitleaks version mismatch" >&2; exit 2; }

echo "== pytest =="
# test_public_files_carry_no_private_task_local_denylist_terms needs a private term list that is
# never committed (MELANGE_IMPORT_PRIVATE_DENYLIST), so it cannot run in CI; it is the only
# deselected test and it stays a local check.
cd tests
python3 -m pytest -q \
  --deselect structural/test_melange_import_synthesis.py::test_public_files_carry_no_private_task_local_denylist_terms
