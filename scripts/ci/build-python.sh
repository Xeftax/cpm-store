#!/usr/bin/env bash
# The Python build gate: every package under the import roots imports in the project's
# environment.
#
# Usage: build-python.sh [ROOT_GLOB|MODULE...]   (default: src)
#
# Each argument is a directory glob whose subdirectories are importable packages —
# `src` for the usual layout, `'libs/*/src'` for a monorepo. A glob matching nothing is
# skipped; matching nothing at all is a failure, since nothing would be verified.
#
# An argument that is a dotted name and not a directory (`my_app.server`) is imported
# as named, after the roots: the package alone only runs its `__init__`, and a server's
# imports are where a production-only failure shows. Same environment, same verdict.
#
# The check a missing runtime dependency fails, which a test suite run with every dev
# group installed does not. Packages whose name starts with `_` are private and skipped.
#
# Always in a production environment: `--no-default-groups` drops every default group, not
# just `dev`, and `--exact` makes that real — a plain `uv run --no-dev` leaves whatever an
# earlier `uv sync` installed in place (measured: pytest stays importable), which is exactly
# the dev-only import this check exists to catch. Extras stay: a deployment can ship one
# (`--all-extras` is the superset), and the base check installs them too.
#
# The environment is a throwaway one (`UV_PROJECT_ENVIRONMENT`), removed on exit: `--exact`
# in the project's own `.venv` would strip a developer's dev tools on every local run.
set -euo pipefail

UV_PROJECT_ENVIRONMENT="$(mktemp -d)/venv"
export UV_PROJECT_ENVIRONMENT
trap 'rm -rf "$(dirname "$UV_PROJECT_ENVIRONMENT")"' EXIT

[[ $# -gt 0 ]] || set -- src

failed=()
modules=()
found=0
for pattern in "$@"; do
  if [[ "$pattern" =~ ^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$ && ! -d "$pattern" ]]; then
    modules+=("$pattern")
    continue
  fi
  # Unquoted on purpose: the argument is a glob, expanded here.
  # shellcheck disable=SC2206
  roots=($pattern)
  for root in "${roots[@]}"; do
    [[ -d "$root" ]] || continue
    for pkg_dir in "$root"/*/; do
      [[ -d "$pkg_dir" ]] || continue
      pkg=$(basename "$pkg_dir")
      [[ "$pkg" == _* ]] && continue
      found=$((found + 1))
      echo "Importing $pkg from $root..."
      uv run --no-default-groups --exact --all-extras python -c "import $pkg" || failed+=("$pkg")
    done
  done
done

for module in ${modules[@]+"${modules[@]}"}; do
  found=$((found + 1))
  echo "Importing $module..."
  uv run --no-default-groups --exact --all-extras python -c "import $module" || failed+=("$module")
done

if [[ $found -eq 0 ]]; then
  echo "::error::build-python.sh: no package under $* — nothing would be verified" >&2
  exit 1
fi
if [[ ${#failed[@]} -gt 0 ]]; then
  echo "::error::could not import: ${failed[*]}" >&2
  exit 1
fi
echo "$found package(s) imported."
