#!/usr/bin/env bash
# The `--hook` mode every check script shares: what a Claude Code hook calls.
#
# Sourced, not executed. A plugin's hook runs the repo's own script with `--hook` and the
# hook payload on stdin, so a session checks what pre-commit and CI check, with the same
# script. In that mode a script:
#
# - moves to the root of the tree the session is in (`hook_enter`, from the payload), and
#   does nothing, silently, outside a git tree;
# - limits itself to what that tree has uncommitted (`hook_changed`) — once something is
#   committed it belongs to pre-commit and CI — and says nothing when that is none of its
#   files;
# - writes everything to stderr, the stream Claude Code shows for a failing hook;
# - never exits 2 (`hook_exit`), the status Claude Code reads as "refuse to stop".
#
# The payload is parsed by hook_payload.py beside this file; this file only sequences commands.

HOOK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_PAYLOAD=""

# hook_enter — read the payload and cd to the session's tree root. Returns 1 outside one.
hook_enter() {
  exec 1>&2
  [[ -t 0 ]] || HOOK_PAYLOAD="$(cat || true)"
  local root
  root="$(printf '%s' "$HOOK_PAYLOAD" | uv run --script "$HOOK_LIB_DIR/hook_payload.py" root)" || return 1
  cd "$root" || return 1
}

# hook_file — the file the tool call wrote, empty when there is none.
hook_file() {
  printf '%s' "$HOOK_PAYLOAD" | uv run --script "$HOOK_LIB_DIR/hook_payload.py" file
}

# hook_changed <pathspec…> — uncommitted paths, NUL-separated: tracked modifications and
# untracked files git does not ignore, never a deletion (a tool handed a path that is gone
# errors, or skips it and reports a clean run). Both halves tolerate a repo with no commit.
hook_changed() {
  git diff -z --name-only --diff-filter=d HEAD -- "$@" 2> /dev/null || true
  git ls-files -z --others --exclude-standard -- "$@" 2> /dev/null || true
}

# hook_files <array-name> <pathspec…> — `hook_changed` into an array, in a loop bash 3.2
# (macOS) runs: it has no `mapfile -d`.
hook_files() {
  local name="$1" f
  shift
  eval "$name=()"
  while IFS= read -r -d '' f; do eval "$name+=(\"\$f\")"; done < <(hook_changed "$@")
}

# hook_any_changed <pathspec…> — whether anything under the pathspecs is uncommitted.
hook_any_changed() {
  [[ "$(hook_changed "$@" | head -c 1 | wc -c)" -gt 0 ]]
}

# hook_exit <status> — exit with it, 2 folded into 1.
hook_exit() {
  local status="$1"
  [[ "$status" -ne 2 ]] || status=1
  exit "$status"
}
