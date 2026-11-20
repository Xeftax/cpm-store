#!/usr/bin/env bash
# review-required : at least one commit of the range must carry a `Reviewed-By: <owner-id>`
# trailer. That commit is the review commit — typically an empty commit:
#
#   git commit --allow-empty -m "review: PR #N — <what was checked>" -m "Reviewed-By: <owner-id>"
#
# The owners to consult for a diff are listed by scripts/ci/review-owners.py
# (map: .vibe/review/owners-map.toml). Together with the branch-protection setting
# last-push-approval ("require approval of the most recent reviewable push"), this
# guarantees every PR gets a review before merge. Convention documented in AGENTS.md
# (section Git) and owned by .vibe/skills/git-workflow-owner.
#
# Usage: check-review-commit.sh [base] [head]    (default: origin/main HEAD)
set -euo pipefail

base="${1:-origin/main}"
head="${2:-HEAD}"
range="$base...$head"

if ! git merge-base --is-ancestor "$base" "$head" 2>/dev/null; then
  echo "review-required: $base is not an ancestor of $head -> empty range, OK"
  exit 0
fi

cd "$(git rev-parse --show-toplevel)"
count=0
for c in $(git rev-list "$range"); do
  count=$((count + 1))
  trailer=$(git log -1 --format='%B' "$c" | grep -E '^Reviewed-By: ' | head -1 || true)
  owner_id="${trailer#Reviewed-By: }"
  # the trailer value must be a known owner id from .vibe/review/owners-map.toml
  if [[ -n "$owner_id" ]] && grep -qF "id = \"$owner_id\"" .vibe/review/owners-map.toml; then
    short=$(git rev-parse --short "$c")
    echo "review-required: OK — review commit $short carries '$trailer' ($count commits scanned in $range)"
    exit 0
  fi
done

echo "review-required: no commit in $range carries a 'Reviewed-By: <owner-id>' trailer" >&2
echo "Add an empty review commit, e.g.:" >&2
echo "  git commit --allow-empty -m 'review: <what was checked>' -m 'Reviewed-By: <owner-id>'" >&2
echo "where <owner-id> is an id from .vibe/review/owners-map.toml" >&2
exit 1
