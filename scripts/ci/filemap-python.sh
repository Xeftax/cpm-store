#!/usr/bin/env bash
# filemap-python.sh — write the Python section of docs/FILEMAP.
#
# A stable entry point: the `filemap` check and the Claude Code Stop hooks call this
# path, and the generator behind it is lib/filemap_core.py, resolved relative to this
# file. The tree to index is the hook JSON's `cwd` on stdin, then CLAUDE_PROJECT_DIR,
# then PWD — a CI caller has no hook JSON, so it exports CLAUDE_PROJECT_DIR itself.
#
# Usage: filemap-python.sh [source_dirs...]
# Default: scans the entire repo (git ls-files respects .gitignore)

set -euo pipefail

# Not `exec`: uv exits 2 when it cannot start the script (no Python 3.13 reachable,
# offline), and as a Stop hook 2 stops the session from ending. The script itself never
# exits 2, so a 2 here is always uv's, and becomes a non-blocking 1.
status=0
uv run --script "$(dirname "${BASH_SOURCE[0]}")/lib/filemap_core.py" --lang python "$@" || status=$?
[[ $status -ne 2 ]] || status=1
exit "$status"
