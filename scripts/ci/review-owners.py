#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""review-owners: print the review owners (skills in .vibe/skills/) triggered by a diff.

The map is .vibe/review/owners-map.toml: each [[owner]] has id, description, and
triggers — `paths` (globs matched against the changed files) and `contains`
(substrings matched against the added lines of the diff).

Modes:
  --check BASE HEAD   CI: owners for the range (PR base...head)
  --hook              session hook: owners for the uncommitted changes (payload on stdin)
  (no args)           owners for origin/main...HEAD

Always exit 0: informational — printed in the `review-owners` CI job log and by the
Vibe `review-owners` hook, so the agent opening/reviewing a PR or pushing gets the
list of owners to spawn (agents.spawn, instructions = the owner's SKILL.md).
"""

import fnmatch
import json
import subprocess
import sys
import tomllib
from pathlib import Path

MAP = ".vibe/review/owners-map.toml"
EXIT_USAGE = 2
# how many matched paths are shown per owner before the "..." truncation marker
MAX_SHOWN_PATHS = 3


def _git(root: Path, *args: str) -> str:
    """Run git in root and return its stdout."""
    done = subprocess.run(  # noqa: S603 -- fixed argv
        ["git", "-C", str(root), *args],  # noqa: S607 -- git from PATH
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout


def _git_root(start: Path) -> Path:
    """Return the working tree root above start, or start itself outside one."""
    out = _git(start, "rev-parse", "--show-toplevel").strip()
    return Path(out) if out else start


def _changed(root: Path, ref_args: list[str]) -> tuple[list[str], list[str]]:
    """Return (changed files, added lines) for a git diff range."""
    files = _git(root, "diff", "--name-only", *ref_args).split()
    diff = _git(root, "diff", "-U0", "--no-color", *ref_args)
    added = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    return files, added


def _payload_root() -> Path:
    """Session tree root from the hook payload on stdin (payload cwd -> git root)."""
    if sys.stdin.isatty():
        return _git_root(Path.cwd())
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return _git_root(Path.cwd())
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if isinstance(cwd, str) and cwd and Path(cwd).is_dir():
        return _git_root(Path(cwd))
    return _git_root(Path.cwd())


def _triggered_owners(root: Path, files: list[str], added: list[str]) -> list[tuple[str, str, str]]:
    """Return (id, description, evidence) for every owner whose triggers match the diff."""
    owners = tomllib.loads((root / MAP).read_text(encoding="utf-8"))["owner"]
    added_text = "\n".join(added)
    triggered: list[tuple[str, str, str]] = []
    for owner in owners:
        evidence = [f for f in files if any(fnmatch.fnmatch(f, g) for g in owner.get("paths", []))]
        hits = [s for s in owner.get("contains", []) if s in added_text]
        if evidence or hits:
            why: list[str] = []
            if evidence:
                shown = ", ".join(evidence[:MAX_SHOWN_PATHS])
                if len(evidence) > MAX_SHOWN_PATHS:
                    shown += " ..."
                why.append(f"paths: {shown}")
            if hits:
                why.append(f"contains: {', '.join(hits)}")
            triggered.append((owner["id"], owner["description"], "; ".join(why)))
    return triggered


def _print(triggered: list[tuple[str, str, str]], label: str) -> None:
    """Print the triggered owners with their evidence."""
    print(f"review-owners: {len(triggered)} owner(s) triggered by {label}:")
    for oid, desc, reason in triggered:
        print(f"  - {oid} — {desc}")
        print(f"      triggered by: {reason}")
    if not triggered:
        print("  (none)")


def _run_hook(root: Path) -> int:
    """Owners for the uncommitted changes (session-hook mode)."""
    files, added = _changed(root, ["HEAD"])
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").split()
    files = sorted(set(files) | set(untracked))
    _print(_triggered_owners(root, files, added), "uncommitted changes")
    return 0


def _run_check(root: Path, refs: list[str]) -> int:
    """Owners for the range BASE...HEAD; refs are the two refs after --check."""
    try:
        base, head = refs
    except ValueError:
        print("usage: review-owners.py --check BASE HEAD", file=sys.stderr)
        return EXIT_USAGE
    files, added = _changed(root, [f"{base}...{head}"])
    _print(_triggered_owners(root, files, added), f"{base}...{head}")
    return 0


def main() -> int:
    """Dispatch on the mode flag; the default is the origin/main...HEAD range."""
    args = sys.argv[1:]
    mode = args[0] if args else ""
    if mode == "--hook":
        return _run_hook(_payload_root())
    if mode == "--check":
        return _run_check(_git_root(Path.cwd()), args[1:])
    files, added = _changed(_git_root(Path.cwd()), ["origin/main...HEAD"])
    _print(_triggered_owners(_git_root(Path.cwd()), files, added), "origin/main...HEAD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
