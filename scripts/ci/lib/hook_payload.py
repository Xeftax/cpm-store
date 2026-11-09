#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Read a Claude Code hook payload for the check scripts' `--hook` mode.

Two questions, each answered on stdout from the payload on stdin:

    hook_payload.py root   the git root of the tree the session is in; exit 1 when there is none
    hook_payload.py file   the file a PostToolUse Edit/Write call wrote; empty when there is none

The tree comes from the payload's `cwd`, not `$CLAUDE_PROJECT_DIR`: that stays on the
directory the session started in, so a worktree session would be checked against the main
checkout. It is resolved up to the git root, because the payload's `cwd` also follows any
`cd` the turn ran, and every script reads its configs from the root. A payload that is
missing, malformed or names no directory falls back to `$CLAUDE_PROJECT_DIR`, then the
current directory, so a script run by hand still finds its tree.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def _payload(text: str) -> dict[str, object]:
    """Parse the payload, empty when it is not a JSON object."""
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def session_dir(payload: str) -> Path:
    """Return the directory the session is in."""
    cwd = _payload(payload).get("cwd")
    if isinstance(cwd, str) and cwd and Path(cwd).is_dir():
        return Path(cwd)
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())


def tree_root(directory: Path) -> Path | None:
    """Return the working tree root above `directory`, or None outside one."""
    done = subprocess.run(  # noqa: S603 -- fixed argv
        ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],  # noqa: S607 -- git from PATH
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None


def written_file(payload: str) -> str:
    """Return the tool call's `file_path`, accepting the camelCase spelling some payloads use."""
    tool_input = _payload(payload).get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    value = tool_input.get("file_path", tool_input.get("filePath", ""))
    return value if isinstance(value, str) else ""


def main(argv: list[str]) -> int:
    """Answer the question `argv` names about the payload on stdin."""
    payload = sys.stdin.read()
    if argv == ["root"]:
        root = tree_root(session_dir(payload))
        if root is None:
            return 1
        print(root)
        return 0
    if argv == ["file"]:
        print(written_file(payload))
        return 0
    print("usage: hook_payload.py root|file  (hook payload on stdin)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
