#!/usr/bin/env bash
# Shared mdformat invocation, and the one place the markdown formatter's version is
# declared.
#
# Usage: format-markdown.sh <file…> | --hook
#
# --hook: a Claude Code hook's call, payload on stdin — see lib/hook-mode.sh. The Markdown file
# the tool call just wrote, and nothing for any other file.
#
# Files are required, and the pre-commit hook passes them. Measured: `mdformat` with no
# argument prints "No files have been passed in. Doing nothing." and exits 0 — so a
# caller that forgets them gets a green run over nothing, not a full-tree format.
#
# The pre-commit hook used to run `uvx --with mdformat-gfm --with mdformat-tables --with
# mdformat-frontmatter mdformat` with no version constraint at all, against a project
# pinning `mdformat>=0.7.22` plus the same three plugins. Two unrelated resolutions of
# the same tool: a developer's hook could format a file one way and the project's own
# environment another, and each would hand it back to the other forever. The versions
# below are what both callers get.
#
# Exact pins, not the `>=` specifiers `pyproject.toml` carries: a floor is the right
# shape for a dependency a project resolves once and locks, and the wrong shape for a
# formatter invoked from an ephemeral `uvx` environment that re-resolves on every run —
# there, `>=` means "whatever released most recently", which is precisely the silent
# disagreement this file exists to remove. `tests/test_shared_scripts.py` asserts these
# stay compatible with what `pyproject.toml` declares, so raising one is not a place the
# two can drift apart unnoticed — `test_the_markdown_pins_satisfy_what_the_project_declares`.
#
# `uvx` rather than `uv run`, inherited from the hook this replaces and still right: a
# repo with no Python environment at all still has a README to format.
set -euo pipefail

MDFORMAT_VERSION="0.7.22"
MDFORMAT_GFM_VERSION="1.0.0"
MDFORMAT_TABLES_VERSION="1.0.0"
MDFORMAT_FRONTMATTER_VERSION="2.1.2"

if [[ "${1:-}" == "--hook" ]]; then
  source "$(dirname "${BASH_SOURCE[0]}")/lib/hook-mode.sh"
  hook_enter || exit 0
  file="$(hook_file)"
  [[ "$file" == *.md && -f "$file" ]] || exit 0
  status=0
  uvx \
    --with "mdformat-gfm==${MDFORMAT_GFM_VERSION}" \
    --with "mdformat-tables==${MDFORMAT_TABLES_VERSION}" \
    --with "mdformat-frontmatter==${MDFORMAT_FRONTMATTER_VERSION}" \
    "mdformat==${MDFORMAT_VERSION}" "$file" || status=$?
  hook_exit "$status"
fi

exec uvx \
  --with "mdformat-gfm==${MDFORMAT_GFM_VERSION}" \
  --with "mdformat-tables==${MDFORMAT_TABLES_VERSION}" \
  --with "mdformat-frontmatter==${MDFORMAT_FRONTMATTER_VERSION}" \
  "mdformat==${MDFORMAT_VERSION}" "$@"
