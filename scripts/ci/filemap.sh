#!/usr/bin/env bash
# Regenerate docs/FILEMAP: one section per language the tree actually has.
#
# Usage: filemap.sh [--hook]
#
# --hook: a Claude Code hook's call, payload on stdin — see lib/hook-mode.sh. The tree's root,
# from wherever the session's cwd drifted to.
#
# Whether the index is stale is not this script's to say: the check's mode compares the
# regenerated file with the committed one, and commits it onto a PR or fails.
#
# ponytail: the languages are read off the tracked files, not off `dockyard.toml` — a tree
# with tracked `.py` files gets a Python section, one with `.ts`/`.tsx` a TypeScript one.
# Read the declaration instead if a repo ever tracks a language it does not want indexed.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--hook" ]]; then
  source "$here/lib/hook-mode.sh"
  hook_enter || exit 0
fi
# The generators resolve the tree from CLAUDE_PROJECT_DIR when no hook JSON is on stdin.
export CLAUDE_PROJECT_DIR="$PWD"

ran=0
if [[ -n "$(git ls-files '*.py' | head -1)" ]]; then
  "$here/filemap-python.sh" < /dev/null
  ran=1
fi
if [[ -n "$(git ls-files '*.ts' '*.tsx' | head -1)" ]]; then
  "$here/filemap-typescript.sh" < /dev/null
  ran=1
fi
[[ $ran -eq 1 ]] || echo "filemap.sh: no Python or TypeScript file tracked — nothing to index."
