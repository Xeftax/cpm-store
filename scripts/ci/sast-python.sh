#!/usr/bin/env bash
# Shared bandit invocation for both the pre-commit hook and the `security-python` check.
#
# Usage: sast-python.sh [--json | --hook]
#
# With no flag the script picks the mode from where it runs. Off a runner it is the hook
# described next. With `CI=true` it writes the reports `--json` writes and then applies the
# CI verdict itself — fail on a HIGH finding, and only on one — so the check needs no step
# of its own around it.
#
# Targets come from git, not a directory walk: .gitignore already keeps .venv,
# node_modules and Claude Code worktrees out, and no layout is assumed, so code outside a
# src/ package (app/, entrypoints/) is scanned instead of silently missed. A NUL-delimited
# `read -d ''` loop, not an unquoted `$(git ls-files ...)` or a bash array built with
# `mapfile -d ''`: word splitting turned `pkg/my file.py` into two nonexistent paths,
# which bandit *skips* rather than failing on — so the file went unscanned and the run
# still looked clean. `read -d ''` works under the bash 3.2 that `pre-commit`'s
# `language: system` resolves to on macOS (no `mapfile -d` there) and under the bash a
# GitHub `ubuntu-latest` runner ships.
#
# Default (no flag): the local pre-commit gate — one bandit run at the `-ll` threshold,
# exit code is the verdict, nothing written to disk.
#
# --json: a full JSON report plus a markdown summary table, so bandit's own exit code
# (non-zero on *any* finding, not just the ones that should block) is swallowed here.
set -euo pipefail

# `--exclude ""` on every bandit call below. bandit's own default (`.svn,CVS,.bzr,.hg,
# .git,__pycache__,.tox,.eggs,*.egg`) is applied as a plain substring of the whole path,
# and a value is rewritten to a directory glob only when it names an existing DIRECTORY.
# `.git` is a FILE in a linked worktree, so there it stays a bare substring and silently
# drops every `.github/...` path from the scan; `.hg`, `.tox`, `CVS` and `.eggs` do the
# same wherever they are not a directory at the root. The targets come from `git ls-files`,
# which already leaves out what those names stand for, so emptying the default loses
# nothing. bandit.toml's `exclude_dirs` is the one place an exclusion is written.
bandit_base=(-c bandit.toml --exclude "")

# --hook: a Claude Code hook's call, payload on stdin — see lib/hook-mode.sh. The local gate's
# threshold, over the uncommitted .py files: a finding is per-file, never transitive.
if [[ "${1:-}" == "--hook" ]]; then
  source "$(dirname "${BASH_SOURCE[0]}")/lib/hook-mode.sh"
  hook_enter || exit 0
  hook_files files '*.py'
  [[ ${#files[@]} -gt 0 ]] || exit 0
  status=0
  uv run bandit "${bandit_base[@]}" -ll "${files[@]}" || status=$?
  hook_exit "$status"
fi

py_files=()
while IFS= read -r -d '' f; do py_files+=("$f"); done < <(git ls-files -z '*.py')

if [[ ${#py_files[@]} -eq 0 ]]; then
  echo "::error::No tracked Python file found — bandit would scan nothing. Failing instead of reporting a clean scan." >&2
  exit 1
fi

mode="${1:-}"
if [[ -z "$mode" && "${CI:-}" == "true" ]]; then mode=verdict; fi

if [[ "$mode" != "--json" && "$mode" != verdict ]]; then
  exec uv run bandit "${bandit_base[@]}" -ll "${py_files[@]}"
fi

echo "Scanning ${#py_files[@]} tracked Python files"
uv run bandit "${bandit_base[@]}" "${py_files[@]}" -f json -o bandit-report.json || true

if [[ ! -f bandit-report.json ]]; then
  echo "::error::bandit produced no JSON report — treating as a failed scan rather than a clean one." >&2
  exit 1
fi

# A markdown table, not the raw `-f txt` dump: that form opens with seven `[main] INFO`
# lines and a progress bar, then spends four lines and a source excerpt per finding — ten
# LOW findings made an unscannable wall in the PR comment. Everything needed is already
# in the JSON produced above.
# Summary and verdict live in scan_report.py, shared with the other SAST script: it
# writes bandit-summary.md, prints it, and in verdict mode fails on a top-severity finding.
args=(--tool bandit --report bandit-report.json --summary bandit-summary.md)
if [[ "$mode" == verdict ]]; then args+=(--verdict); fi
uv run --script "$(dirname "${BASH_SOURCE[0]}")/lib/scan_report.py" "${args[@]}"
