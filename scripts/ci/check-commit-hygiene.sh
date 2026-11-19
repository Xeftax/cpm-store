#!/usr/bin/env bash
# commit-hygiene : bloque les contournements de hooks pre-commit dans les commits d'un range.
#
# Règle (AGENTS.md section Git + .vibe/skills/git-workflow-owner) : jamais de
# `git commit --no-verify` sans autorisation explicite par chat. git n'enregistre pas
# si les hooks ont tourné, donc la convention rend tout bypass visible : un commit qui
# contourne les hooks DOIT porter le trailer `Hooks-Bypassed: <hook> — <raison>`.
# Ce script échoue si un message de commit du range contient `--no-verify` ou
# `Hooks-Bypassed` : un bypass autorisé par chat se traduit par un reword humain du
# message (qui retire le marqueur) après validation, jamais par un merge en l'état.
#
# Usage: check-commit-hygiene.sh [base] [head]    (défaut: origin/main HEAD)
set -euo pipefail

base="${1:-origin/main}"
head="${2:-HEAD}"
range="$base...$head"

if ! git merge-base --is-ancestor "$base" "$head" 2>/dev/null; then
  echo "commit-hygiene: $base n'est pas un ancêtre de $head -> range vide, OK"
  exit 0
fi

bad=0
for c in $(git rev-list "$range"); do
  if git log -1 --format='%B' "$c" | grep -qE -- '--no-verify|Hooks-Bypassed'; then
    echo "commit-hygiene: $c déclare un contournement de hooks :" >&2
    git log -1 --format='%B' "$c" >&2
    bad=1
  fi
done
if [[ "$bad" -ne 0 ]]; then
  exit 1
fi
echo "commit-hygiene: OK ($(git rev-list --count "$range") commits scannés dans $range, aucun contournement de hooks)"
