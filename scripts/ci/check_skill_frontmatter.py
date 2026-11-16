#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["pyyaml>=6"]
# ///
"""Fail CI when a SKILL.md carries frontmatter Claude cannot route on.

Claude Code builds its skill listing at session start from each ``SKILL.md``
frontmatter, so that header, not any table in a doc, decides whether a skill can
be selected from a natural request. A header that is missing, misnamed, or
silently truncated makes the skill unreachable while the file still looks
complete, which is invisible on review and produces no error anywhere.

That is not hypothetical: a description reading ``Reconcile the Project #5 board
with ...`` is cut at the space-preceded ``#`` by YAML, so the description actually
loaded was 33 characters and every trigger phrase was discarded. Parsing the header
with a real YAML loader and asserting the description survived it catches that and
every other way a value can be cut short, rather than pattern-matching the one
syntax that caused it.

Skills are read from ``.claude/skills`` unless the command line names other roots: each
argument is a directory or a glob, relative to the repo root, whose subdirectories are the
skills (``plugins/*/skills`` for a repo that ships plugins). A repo with no matching
directory has nothing to check and passes.
"""

import re
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

DEFAULT_ROOTS = (".claude/skills",)
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

# Every real description states what the skill does and when to reach for it, so it runs
# to a few hundred characters. A value this short means the text was cut off (by an
# unquoted `#`, a stray colon, a broken block scalar), not that someone wrote a terse but
# usable one.
_MIN_DESCRIPTION = 40


def _problems_with(directory: Path, label: str) -> list[str]:
    """List what is wrong with one skill's frontmatter; empty means Claude can route on it.

    `label` is where the skill lives, relative to the repo, so a report names the right one
    when two plugins ship a skill of the same name.
    """
    skill_md = directory / "SKILL.md"
    if not skill_md.is_file():
        return [f"{label} has no SKILL.md."]

    header = _FRONTMATTER.match(skill_md.read_text())
    try:
        frontmatter = yaml.safe_load(header.group(1)) if header else None
    except yaml.YAMLError as error:
        return [f"{label}: frontmatter is not valid YAML ({error.__class__.__name__})."]
    if not isinstance(frontmatter, dict):
        return [
            f"{label}: no YAML frontmatter, so the skill is listed with nothing but its "
            "heading and can never be selected from a natural request. Add a name and a description."
        ]

    problems = []
    if frontmatter.get("name") != directory.name:
        problems.append(f"{label}: declares name={frontmatter.get('name')!r}, which must be the directory name.")
    description = str(frontmatter.get("description") or "").strip()
    if len(description) < _MIN_DESCRIPTION:
        problems.append(
            f"{label}: description parses to {len(description)} characters, so it is empty or "
            "was silently truncated, most often by an unquoted '#', which YAML reads as a comment. "
            "It is the trigger text, so the skill is unselectable without it."
        )
    return problems


def _skill_directories(root: Path, patterns: Sequence[str]) -> list[Path]:
    """Every skill directory under the roots the patterns name, in a stable order."""
    roots = sorted({match for pattern in patterns for match in root.glob(pattern) if match.is_dir()})
    return [path for skills in roots for path in sorted(skills.iterdir()) if path.is_dir()]


def main(root: Path | None = None, skill_roots: Sequence[str] = ()) -> int:
    """Check every skill under `skill_roots` (default `.claude/skills`); 0 when all are routable or there are none."""
    base = root or Path.cwd()
    patterns = tuple(skill_roots) or DEFAULT_ROOTS
    absolute = [pattern for pattern in patterns if Path(pattern).is_absolute()]
    if absolute:
        print(f"skill-frontmatter: skill roots are relative to the repo, got {', '.join(absolute)}.", file=sys.stderr)
        return 2

    if not any(match.is_dir() for pattern in patterns for match in base.glob(pattern)):
        print(f"skill-frontmatter: no skill directory matching {', '.join(patterns)} in this repo, nothing to check.")
        return 0

    directories = _skill_directories(base, patterns)
    problems = [
        problem
        for directory in directories
        for problem in _problems_with(directory, directory.relative_to(base).as_posix())
    ]
    if problems:
        joined = "\n".join(f"  - {problem}" for problem in problems)
        print(
            f"::error::{len(problems)} problem(s) in skill frontmatter Claude cannot route on:\n{joined}",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {len(directories)} skills carry a matching name and an intact description.")
    return 0


if __name__ == "__main__":
    sys.exit(main(None, sys.argv[1:]))
