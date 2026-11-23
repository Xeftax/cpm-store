#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""language check: this repository is English-only.

Every line ADDED by a change is scanned for French text — accented characters plus a
stopword list, since accent-free French is invisible to the character class — and
reported as `path:line: ...`. Modes:

  (no args)          pre-commit: staged changes (`git diff --cached`)
  --check BASE HEAD  CI: `git diff BASE...HEAD`
  --hook [PATH...]   session hook: uncommitted changes (payload on stdin, output on
                     stderr, never exit 2); PATH... limits the scan
  --pre-write        pre_tool hook on write_file/edit: scans the content being written
                     (payload on stdin); always exit 0 — a warning, not a block

The patterns are written with escapes so this file itself stays ASCII-clean.
Excluded (generated/vendored): **/Cargo.lock, docs/TREE.md, reports/**, **/target/**,
and this detector itself (it lists the French words it matches).
"""

import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from typing import TextIO

# Latin-1 accented letters (minus the multiplication/division signs), Latin Extended-A,
# French quotes and typographic apostrophes/quotes. Section sign (U+00A7) and em-dash
# (U+2014) are deliberately NOT in the class: they are used in English comments here.
FRENCH = re.compile(r"[\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff\u0100-\u017f\u00ab\u00bb\u2018\u2019\u201c\u201d]")
# High-signal French words, matched as whole words (escapes keep this file ASCII-clean).
FRENCH_WORDS = re.compile(
    r"\b(voir|idem|deserialisation|des\u00e9rialisation|serialisation|s\u00e9rialisation"
    r"|m\u00e9thode|methode|fonction|commentaire|banni\u00e8re|banniere|champ"
    r"|au-dessus|au dessus|ci-dessus|ci-dessous|en-dessous|en dessous"
    r"|unicit\u00e9|doublon|cl\u00e9|pr\u00e9serv\u00e9)\b"
)
FRENCH_RE = re.compile(f"(?:{FRENCH.pattern})|(?:{FRENCH_WORDS.pattern})")
EXCLUDED = [
    "**/Cargo.lock",
    "docs/TREE.md",
    "reports/**",
    "**/target/**",
    # the detector itself lists the French words it matches
    "scripts/ci/check-language.py",
]
EXIT_USAGE = 2
# unified-diff hunk header `@@ -a,b +c,d @@` has three space-separated fields before the
# optional trailing context
HUNK_HEADER_FIELDS = 3


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


def _is_excluded(path: str) -> bool:
    """Return True when path matches an excluded (generated/vendored) glob."""
    return any(fnmatch.fnmatch(path, pat) for pat in EXCLUDED)


def _parse_added(diff: str) -> "Iterator[tuple[str, int, str]]":
    """Yield (path, new_lineno, text) for every added line of a unified diff."""
    path = None
    lineno = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[len("+++ b/") :]
        elif line.startswith("+++"):
            path = None
        elif line.startswith("@@"):
            parts = line.split(" ")
            if len(parts) >= HUNK_HEADER_FIELDS and parts[2].startswith("+"):
                lineno = int(parts[2][1:].split(",")[0])
        elif path is not None:
            if line.startswith("+"):
                yield path, lineno, line[1:]
                lineno += 1
            elif not line.startswith("-"):
                lineno += 1


def _scan(pairs: "Iterable[tuple[str, int, str]]") -> list[tuple[str, int, str]]:
    """Return the pairs whose text matches the French detector."""
    out: list[tuple[str, int, str]] = []
    for path, lineno, text in pairs:
        if _is_excluded(path):
            continue
        if FRENCH_RE.search(text):
            out.append((path, lineno, text.strip()))
    return out


def _report(violations: list[tuple[str, int, str]], stream: "TextIO") -> int:
    """Print one problem per violation on stream; return 1 when there are any."""
    for path, lineno, text in violations:
        print(
            f"{path}:{lineno}: French/accented characters in an added line (repo is English-only): {text}",
            file=stream,
        )
    return 1 if violations else 0


def _diff_added(root: Path, ref_args: list[str], pathspec: list[str]) -> "Iterator[tuple[str, int, str]]":
    """Yield the added lines of `git diff -U0 ref_args -- pathspec`."""
    diff = _git(root, "diff", "-U0", "--no-color", *ref_args, "--", *pathspec)
    yield from _parse_added(diff)


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


def _run_pre_write() -> int:
    """Scan the content of a write_file/edit payload; always return 0 (warning only)."""
    if sys.stdin.isatty():
        return 0
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path") or ""
    content = tool_input.get("content") or tool_input.get("new_string") or ""
    if path and not _is_excluded(path):
        for i, line in enumerate(content.splitlines(), 1):
            if FRENCH_RE.search(line):
                print(
                    f"{path}:{i}: French/accented characters in written content "
                    f"(repo is English-only): {line.strip()}",
                    file=sys.stderr,
                )
    return 0


def _run_hook(root: Path, pathspec: list[str]) -> int:
    """Scan uncommitted changes, print on stderr, never exit 2 (session-hook mode)."""
    tracked = _git(root, "diff", "--name-only", "--diff-filter=d", "HEAD", "--", *pathspec).split()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "--", *pathspec).split()
    files = sorted(set(tracked + untracked))
    pairs = list(_diff_added(root, ["HEAD"], files))
    seen = {p for p, _, _ in pairs}
    for f in files:  # untracked files have no diff: scan them whole
        fp = root / f
        if f not in seen and fp.is_file():
            for i, line in enumerate(fp.read_text(errors="replace").splitlines(), 1):
                pairs.append((f, i, line))
    return _report(_scan(pairs), sys.stderr)


def _run_check(root: Path, refs: list[str]) -> int:
    """Scan the range BASE...HEAD; refs are the two refs after --check."""
    try:
        base, head = refs
    except ValueError:
        print("usage: check-language.py --check BASE HEAD", file=sys.stderr)
        return EXIT_USAGE
    ancestor = subprocess.run(  # noqa: S603 -- fixed argv
        ["git", "-C", str(root), "merge-base", "--is-ancestor", base, head],  # noqa: S607
        check=False,
    ).returncode
    if ancestor != 0:
        print(f"language: {base} is not an ancestor of {head} -> empty range, OK")
        return 0
    pairs = list(_diff_added(root, [f"{base}...{head}"], []))
    return _report(_scan(pairs), sys.stdout)


def _run_staged(root: Path) -> int:
    """Scan the staged changes (pre-commit default mode)."""
    pairs = list(_diff_added(root, ["--cached"], []))
    status = _report(_scan(pairs), sys.stdout)
    if status:
        print(
            "language: English-only rule violated on added lines (see above). "
            "Rule and enforcement: AGENTS.md 'Language and style', "
            "scripts/ci/check-language.py",
            file=sys.stderr,
        )
    return status


def main() -> int:
    """Dispatch on the mode flag; the default is the staged (pre-commit) scan."""
    args = sys.argv[1:]
    mode = args[0] if args else ""
    if mode == "--pre-write":
        return _run_pre_write()
    if mode == "--hook":
        return _run_hook(_payload_root(), args[1:])
    if mode == "--check":
        return _run_check(_git_root(Path.cwd()), args[1:])
    return _run_staged(_git_root(Path.cwd()))


if __name__ == "__main__":
    sys.exit(main())
