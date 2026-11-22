#!/usr/bin/env bash
# commit-hygiene : blocks pre-commit hook bypasses in the commits of a range.
#
# Rule (AGENTS.md section Git + .vibe/skills/git-workflow-owner): never
# `git commit --no-verify` without explicit chat authorization. git does not record
# whether hooks ran, so the convention makes any bypass visible: a commit that
# bypasses hooks MUST carry the trailer `Hooks-Bypassed: <hook> — <reason>`.
# This script fails if a commit message of the range contains `--no-verify` or
# `Hooks-Bypassed`: a chat-authorized bypass is translated into a human reword of the
# message (which removes the marker) after validation, never merged as-is.
#
# Usage: check-commit-hygiene.sh [base] [head]    (default: origin/main HEAD)
set -euo pipefail

base="${1:-origin/main}"
head="${2:-HEAD}"
range="$base...$head"

if ! git merge-base --is-ancestor "$base" "$head" 2>/dev/null; then
  echo "commit-hygiene: $base is not an ancestor of $head -> empty range, OK"
  exit 0
fi

bad=0
for c in $(git rev-list "$range"); do
  if git log -1 --format='%B' "$c" | grep -qE -- '--no-verify|Hooks-Bypassed'; then
    echo "commit-hygiene: $c declares a hook bypass:" >&2
    git log -1 --format='%B' "$c" >&2
    bad=1
  fi
done
if [[ "$bad" -ne 0 ]]; then
  exit 1
fi
echo "commit-hygiene: OK ($(git rev-list --count "$range") commits scanned in $range, no hook bypass)"
