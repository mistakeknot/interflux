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
# The guest clone holds only the admitted commit's history and no `main` ref, but the isolation
# tests diff against `main`. For a pull request run, point a local `main` at its base commit
# (CI_BASE_SHA) and fail if that commit is missing from the clone. A run with no base (a push to the
# default branch) has nothing to compare against, so `main` is HEAD and those tests see an empty
# diff; the log says which case ran.
if git rev-parse --verify --quiet refs/heads/main >/dev/null; then
  echo "unexpected pre-existing main ref in the CI clone" >&2; exit 2
fi
if [[ -n "${CI_BASE_SHA:-}" ]]; then
  git cat-file -e "${CI_BASE_SHA}^{commit}" 2>/dev/null || { echo "CI_BASE_SHA ${CI_BASE_SHA} is not in the clone" >&2; exit 2; }
  git branch main "$CI_BASE_SHA"
  echo "isolation tests compare against base ${CI_BASE_SHA}"
else
  git branch main HEAD
  echo "no CI_BASE_SHA: isolation tests compare against HEAD (empty diff)"
fi
export PYTHONDONTWRITEBYTECODE=1
# test_public_files_carry_no_private_task_local_denylist_terms needs a private term list that is
# never committed (MELANGE_IMPORT_PRIVATE_DENYLIST), so it cannot run in CI; it is the only
# deselected test and it stays a local check. The test lives in
# structural/test_melange_import_synthesis.py, which not every admitted commit carries yet. Where
# the file is present the test is deselected and exactly one deselection is required below; where
# the file is absent there is nothing to deselect and none may be reported. The explicit `.`
# collects every test under tests/, including the top-level modules that tests/pyproject.toml
# testpaths leaves out; -ra lists every skip with its reason.
cd tests
out="$work/pytest.out"
deselect_args=()
deselect_expected=0
if [[ -f structural/test_melange_import_synthesis.py ]]; then
  deselect_args=(--deselect structural/test_melange_import_synthesis.py::test_public_files_carry_no_private_task_local_denylist_terms)
  deselect_expected=1
fi
set +e
python3 -m pytest -q -ra -p no:cacheprovider . "${deselect_args[@]}" \
  2>&1 | tee "$out"
rc=("${PIPESTATUS[@]}")
set -e
[[ ${rc[0]} -eq 0 ]] || { echo "pytest failed (exit ${rc[0]})" >&2; exit "${rc[0]}"; }
[[ ${rc[1]} -eq 0 ]] || { echo "could not record the pytest report" >&2; exit 2; }
# A green run must not hide a skip or a deselection that was meant to run. The only accepted skips
# are tests whose optional inputs (Linsenkasten source, Hermes, the real spec corpora) are absent
# from the guest; anything else, an unmatched --deselect and an unexpected deselection fail the check.
if [[ "$deselect_expected" -eq 1 ]]; then
  grep -qE '(^|, )1 deselected( |,|$)' "$out" || { echo "expected exactly the one deselected test" >&2; exit 2; }
else
  ! grep -qE '(^|, )[0-9]+ deselected( |,|$)' "$out" || { echo "unexpected deselected tests" >&2; exit 2; }
fi
accepted='Linsenkasten source package is unavailable|hermes not installed|real (brainstorm )?spec corpus not present'
if grep -E '^SKIPPED' "$out" | grep -vE "$accepted"; then
  echo "unexpected skipped tests (listed above)" >&2; exit 2
fi
