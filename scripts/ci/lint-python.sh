#!/usr/bin/env bash
# Shared ruff invocation for both the pre-commit hook and the `lint-python` check.
#
# Usage: lint-python.sh [--check | --fix | --hook]
#
# With no flag the script picks the mode from where it runs: `--check` when `CI=true`
# (every GitHub runner sets it), `--fix` otherwise. So the hook and the CI check run the
# same command with no argument of their own, and a developer's terminal fixes.
#
# --check: read-only, full project — what CI wants. Runs `ruff check` and
# `ruff format --check` in turn, each captured to its own report file (ruff-check.txt,
# ruff-format.txt), uploaded as the `lint-python` check's artifacts. Both run even if the first fails, and the script exits
# non-zero if either did.
#
# --fix: the writing pair pre-commit wants — `ruff check --fix` then `ruff format`,
# straight to the terminal. No report files: a developer's working tree should not gain
# untracked .txt files on every commit, and pre-commit already shows each command's own
# output.
#
# No --config flag: ruff auto-discovers ./ruff.toml walking up from the working
# directory, and both call sites always run from the repo root — verified byte-identical
# output with and without `--config ruff.toml` from there. Passing it was redundant, not
# a behaviour either call site depended on.
#
# --output-format=github is added to the check step only when $GITHUB_ACTIONS is set
# (GitHub sets it on every Actions runner) — it annotates the diff in GitHub's UI and is
# meaningless on a developer's machine, so detecting it beats a caller-supplied flag that
# would just always be on in CI and always off locally.
set -uo pipefail

mode="${1:-}"

# --hook: a Claude Code hook's call, payload on stdin — see lib/hook-mode.sh. The writing pair,
# on the uncommitted .py files alone: the project-wide `--fix` rewrites every file from
# whatever base the checkout is on, which once left a repo with a 410-file diff reverting
# other people's work. `--force-exclude`, or a named path bypasses ruff's `exclude`.
if [[ "$mode" == "--hook" ]]; then
  source "$(dirname "${BASH_SOURCE[0]}")/lib/hook-mode.sh"
  hook_enter || exit 0
  hook_files files '*.py'
  [[ ${#files[@]} -gt 0 ]] || exit 0
  uv run ruff check --force-exclude --fix --quiet "${files[@]}"
  uv run ruff format --force-exclude --quiet "${files[@]}"
  status=0
  uv run ruff check --force-exclude "${files[@]}" || status=$?
  hook_exit "$status"
fi
if [[ -z "$mode" ]]; then
  if [[ "${CI:-}" == "true" ]]; then mode=--check; else mode=--fix; fi
fi

if [[ "$mode" == "--fix" ]]; then
  uv run ruff check --fix .
  check_status=$?
  uv run ruff format .
  format_status=$?
else
  check_args=(check .)
  [[ "${GITHUB_ACTIONS:-}" == "true" ]] && check_args+=(--output-format=github)
  uv run ruff "${check_args[@]}" > ruff-check.txt 2>&1
  check_status=$?
  cat ruff-check.txt

  uv run ruff format --check . > ruff-format.txt 2>&1
  format_status=$?
  cat ruff-format.txt
fi

[[ $check_status -eq 0 && $format_status -eq 0 ]]
