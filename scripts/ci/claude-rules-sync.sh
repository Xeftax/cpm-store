#!/usr/bin/env bash
# Pull the `.claude/rules` this repo already has from the connected-intelligence plugins.
#
# Usage: claude-rules-sync.sh [source-checkout]   (default: _source, where `_check.yml`
#                                                  checks out the check's `source-repo`)
#
# Layout: plugins/<plugin>/rules/<rel> maps to .claude/rules/<rel>. Only files that already
# exist here are updated — a repo opts into a rule by having it, and this is not the place
# to decide it should gain one. The direction is plugin → repo, and it overwrites: guidance
# that exists only here must be promoted into the plugin first.
set -euo pipefail

source_dir="${1:-_source}"
rules_dir=.claude/rules
# Fewer than this many upstream rules means the checkout or the plugin layout changed,
# not the rules — refusing beats proposing the whole directory as drift.
min_source_rules=5

# Via a file rather than a pipe: a `while read` on the right of a pipe runs in a subshell,
# and the count would be lost with it.
list=$(mktemp)
trap 'rm -f "$list"' EXIT
find "$source_dir/plugins" -path '*/rules/*' -name '*.md' | sort > "$list"
found=$(wc -l < "$list" | tr -d ' ')
if [[ "$found" -lt "$min_source_rules" ]]; then
  echo "::error::only $found rule files under $source_dir (floor $min_source_rules) — refusing to propose this as drift" >&2
  exit 1
fi

while IFS= read -r src; do
  rel="${src#*/rules/}"
  dest="$rules_dir/$rel"
  if [[ -f "$dest" ]]; then
    cp "$src" "$dest"
  else
    echo "skipping $rel — not adopted by this repo"
  fi
done < "$list"
echo "upstream rule files: $found"
