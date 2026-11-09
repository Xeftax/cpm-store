#!/usr/bin/env bash
# Apply dockyard to this repo: `dockyard sync`, whose result the check's mode proposes.
#
# Usage: drift.sh
#
# In dock-yard the CLI is the checkout itself, and sync re-renders what the declarations
# generate. Anywhere else it is installed from `_source`: the check's `source-repo` is
# dock-yard, which `_check.yml` checks out with a read-only token scoped to it alone, so
# this check's own write token never has to reach a second repository.
#
# A file sync refuses as `diverged`, or fails to write, is drift it left in place: sync
# names it and exits 1, so the run fails and nothing is proposed until the repo decides —
# `decline` the file in `dockyard.toml`, or take dockyard's copy with `dockyard sync
# --force`. A partial proposal would read as "the repo is back in sync" once merged.
set -euo pipefail

if [[ -f src/dockyard/sync.py ]]; then
  exec uv run --project . dockyard sync
fi

[[ -f _source/pyproject.toml ]] || {
  echo "drift.sh: no dock-yard checkout under _source — the drift check needs source-repo and the App key" >&2
  exit 1
}
exec uvx --from ./_source dockyard sync
