#!/usr/bin/env bash
# Shared gitlint invocation for both the pre-commit hook and the `gitlint` CI check.
#
# Usage: gitlint.sh [git-revision-range]
#
# No argument: lint origin/main...HEAD, the same range CI lints — the hook and the
# check run the same command with no argument of their own, like every other
# scripts/ci wrapper here. On main itself the range is empty and gitlint exits 0.
#
# Rules live in .gitlint (built-in T5 for the conventional-commit title) plus
# scripts/ci/gitlint_rules.py (custom body rule, loaded via extra-path there).
set -euo pipefail

RANGE="${1:-origin/main...HEAD}"

exec gitlint --commits "${RANGE}"
