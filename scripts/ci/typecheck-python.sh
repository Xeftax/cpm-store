#!/usr/bin/env bash
# Shared mypy invocation for both pre-commit and the `typecheck-python` check.
#
# Usage: typecheck-python.sh [--hook]
#
# No mode: the pre-commit hook and the CI gate already ran the exact same command —
# `mypy --config-file mypy.toml .` — and differed only in argument order, which does not
# change mypy's behaviour (verified: byte-identical output either way). There was nothing
# to parameterise.
#
# THIS SCRIPT IS WHERE THE CHECKED SCOPE IS DECIDED. `mypy.toml` carries no `files` key
# and cannot: mypy reads that key only when the command line named no target, and all
# four call sites reach this script, which names one. Widen the scope here.
set -euo pipefail

# --hook: a Claude Code hook's call, payload on stdin — see lib/hook-mode.sh. Gated on a change
# to a .py or to mypy.toml, never narrowed to the changed files: type errors are transitive.
hook=0
if [[ "${1:-}" == "--hook" ]]; then
  source "$(dirname "${BASH_SOURCE[0]}")/lib/hook-mode.sh"
  hook_enter || exit 0
  hook_any_changed '*.py' mypy.toml || exit 0
  hook=1
fi

status=0
uv run mypy --config-file mypy.toml . || status=$?

# `.github/scripts/` is real Python — `validate_architecture.py` and `validate_exclusions.py`
# are what two CI gates run — and the invocation above has never reached it: mypy skips
# every dot-directory during its own walk, before `exclude` is consulted at all.
# Measured on dockyard's own tree: 66 source files checked, not one of them under
# `.github/`.
#
# It cannot simply join that invocation. A script carrying the same name under both
# `.github/scripts/` and `scripts/` is one module name twice, and mypy answers a
# duplicate by abandoning the whole build — "errors prevented further checking" — so the
# combined run checks neither tree. A second invocation is what gives it its own module
# namespace.
if [ -d .github/scripts ]; then
    targets=(.github/scripts)
    # `src` rides along when the repo has one. Without it the package resolves only
    # through the editable install, whose finder mypy cannot follow; `ignore_missing_imports`
    # then degrades every symbol it exports to `Any`, and `warn_return_any` reports
    # errors on code the full-tree run above passes. Measured here: `.github/scripts`
    # alone invents one in `hatch_build.py`, `.github/scripts src` is clean.
    if [ -d src ]; then
        targets+=(src)
    fi
    uv run mypy --config-file mypy.toml "${targets[@]}" || status=$?
fi

[[ $hook -eq 0 ]] || hook_exit "$status"
exit "$status"
