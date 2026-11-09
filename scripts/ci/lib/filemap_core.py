#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Write one language's section of docs/FILEMAP, leaving every other section in place.

Run through `filemap-python.sh` / `filemap-typescript.sh`, which pass `--lang` and nothing
else: by the `filemap` check in CI, and as a Claude Code Stop hook. Rewrites
`docs/FILEMAP` in the project directory — replaces this language's section where it
already sits, preserves the other sections and their order, and drops any body that
predates sections.

Never exits 2. As a Stop hook, "exit 2 prevents Claude from stopping, continues the
conversation", so a wrong argument would restart the turn instead of reporting itself;
any other non-zero code is non-blocking and surfaces the first line of stderr. That is
also why the arguments are parsed by hand: argparse exits 2 on a usage error.

Locking: the publish takes an exclusive `fcntl.flock` on a lock file in the temp
directory, keyed on the resolved path of the FILEMAP it guards — so it leaves no artifact
in the repository being indexed, and the kernel releases it when the process exits.
"""

import ast
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import NamedTuple

OUTFILE = Path("docs/FILEMAP")
SEPARATOR_RE = re.compile(r"^# ── (.*) ──$")
COLUMN = 36
LOCK_ATTEMPTS = 200  # ~10s, then give up rather than delay the turn
PUBLISH_ATTEMPTS = 5
JSDOC_CODE_RE = re.compile(
    r"^[ \t]*(import |export |const |let |var |function |class |interface |type |enum |declare )",
    re.MULTILINE,
)


class PublishError(Exception):
    """The index could not be written; the message says why."""


class Profile(NamedTuple):
    """What one language indexes, and how it reads a file's description."""

    label: str
    file_re: re.Pattern[str]
    # A directory's own description comes from its index file, which is not listed itself.
    index_re: re.Pattern[str]
    exclude_re: re.Pattern[str]
    describe: Callable[[str, list[str]], str]


def read_source(path: str, warnings: list[str]) -> str:
    """Source text, saying so out loud when the file is not valid UTF-8.

    `errors="replace"` rather than `"ignore"`: an undecodable file still belongs in the
    index, and the replacement keeps the damage visible in FILEMAP itself — a Stop hook's
    stderr goes to a debug log nobody reads.
    """
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        warnings.append(f"filemap-core: warning: {path}: not valid UTF-8 ({exc.reason}), description may be mangled")
        return raw.decode("utf-8", errors="replace")


def describe_python(path: str, warnings: list[str]) -> str:
    """First line of the module docstring."""
    doc = ast.get_docstring(ast.parse(read_source(path, warnings)))
    return doc.strip().split("\n")[0] if doc else ""


def describe_ts(path: str, warnings: list[str]) -> str:
    """First prose line of the file-header JSDoc block — one that precedes any code."""
    content = read_source(path, warnings)
    code = JSDOC_CODE_RE.search(content)
    block = re.search(r"/\*\*(.*?)\*/", content[: code.start() if code else len(content)], re.DOTALL)
    if not block:
        return ""
    for raw_line in block.group(1).splitlines():
        line = re.sub(r"^\s*\*\s?", "", raw_line).strip()
        if line and not line.startswith("@"):
            return line
    return ""


PROFILES = {
    "python": Profile(
        label="Python",
        file_re=re.compile(r"\.py$"),
        index_re=re.compile(r"(^|/)__init__\.py$"),
        exclude_re=re.compile(r"(^|/)__init__\.py$"),
        describe=describe_python,
    ),
    "ts": Profile(
        label="TypeScript / JavaScript",
        file_re=re.compile(r"\.(ts|tsx|js|jsx)$"),
        index_re=re.compile(r"(^|/)index\.(ts|tsx|js|jsx)$"),
        exclude_re=re.compile(r"\.d\.ts$|(^|/)index\.(ts|tsx|js|jsx)$"),
        describe=describe_ts,
    ),
}


def parse_args(argv: list[str]) -> tuple[str, list[str]]:
    """Return (language, source directories); raise ValueError with the usage message."""
    lang = ""
    rest = list(argv)
    while rest and rest[0] == "--lang":
        if len(rest) == 1:
            raise ValueError("--lang needs a value ('python' or 'ts')")
        lang, rest = rest[1], rest[2:]
    if lang not in PROFILES:
        raise ValueError(f"--lang must be 'python' or 'ts' (got '{lang}')")
    return lang, rest or ["."]


def session_cwd(hook_input: str) -> Path:
    """Return the tree the session is in, not the one it started in.

    `$CLAUDE_PROJECT_DIR` does not follow an EnterWorktree, so a worktree session would
    regenerate the main checkout's FILEMAP. The hook JSON's `cwd` does follow it.
    """
    try:
        cwd = json.loads(hook_input).get("cwd") if hook_input else None
    except (json.JSONDecodeError, AttributeError):
        cwd = None
    if isinstance(cwd, str) and cwd and Path(cwd).is_dir():
        return Path(cwd)
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())


def git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git in the current directory, capturing its output."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)  # noqa: S603, S607 -- fixed argv


def repo_name() -> str:
    """Name the repo, not the checkout: the origin URL first, then git's common dir.

    A checkout's folder is whatever its clone was called, and a header that follows it
    makes the FILEMAP check flap between a runner and a laptop over the same tree.
    `--git-common-dir` points at the main `.git` even from a linked worktree.
    """
    origin = git("remote", "get-url", "origin")
    if origin.returncode == 0 and origin.stdout.strip():
        name = origin.stdout.strip().rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        return name.removesuffix(".git")
    common = git("rev-parse", "--git-common-dir")
    if common.returncode == 0 and common.stdout.strip():
        resolved = (Path.cwd() / common.stdout.strip()).resolve()
        # A plain checkout or worktree: the common dir is the repo's own `.git`. A
        # submodule's is `<super>/.git/modules/<name>`, which already carries the name.
        return resolved.parent.name if resolved.name == ".git" else resolved.name
    return Path.cwd().resolve().name


def walk(sources: list[str]) -> list[str]:
    """Every tracked and untracked-but-not-ignored path under `sources`.

    Raises CalledProcessError when git cannot run: a walk that never ran must not reach
    the caller as "this repo has no files of this language", or the FILEMAP gate reports
    success over it. `core.quotePath=false`, or a non-ASCII path arrives octal-escaped and
    silently drops out of the index.
    """
    listed: list[str] = []
    for extra in ([], ["--others", "--exclude-standard"]):
        result = subprocess.run(  # noqa: S603 -- fixed argv
            ["git", "-c", "core.quotePath=false", "ls-files", *extra, *sources],  # noqa: S607 -- git from PATH
            capture_output=True,
            text=True,
            check=True,
        )
        listed.extend(result.stdout.splitlines())
    return listed


def select(walked: list[str], profile: Profile) -> tuple[list[str], list[str]]:
    """Split the walk into (index files, listed files), each sorted and present on disk.

    The index still lists a path moved or deleted without staging; keeping only what is
    on disk stops a moved module being indexed twice.
    """
    candidates = sorted({path for path in walked if profile.file_re.search(path) and Path(path).is_file()})
    index_files = [path for path in candidates if profile.index_re.search(path)]
    listed = [path for path in candidates if not profile.exclude_re.search(path)]
    return index_files, listed


def description(path: str, profile: Profile, warnings: list[str]) -> str:
    """Describe `path`; a file that cannot be parsed is still listed, with a warning."""
    try:
        return profile.describe(path, warnings)
    except Exception as exc:  # noqa: BLE001 -- any unreadable file, one warning each
        warnings.append(f"filemap-core: warning: {path}: {type(exc).__name__}: {exc}")
        return ""


def render_body(entries: list[tuple[str, str]], dir_descs: dict[str, str]) -> list[str]:
    """Render the section body: a tree, one line per directory opened and per file."""
    body: list[str] = []
    prev_parts: list[str] = []
    for filepath, desc in sorted(entries):
        parent = str(PurePosixPath(filepath).parent)
        parts = parent.split("/") if parent != "." else []
        common = 0
        while common < min(len(parts), len(prev_parts)) and parts[common] == prev_parts[common]:
            common += 1
        for depth in range(common, len(parts)):
            indent = "  " * depth
            dir_desc = dir_descs.get("/".join(parts[: depth + 1]), "")
            body.append(
                f"{indent}{parts[depth] + '/':<{COLUMN}} — {dir_desc}" if dir_desc else f"{indent}{parts[depth]}/"
            )
        padded = f"{PurePosixPath(filepath).name:<{COLUMN}}"
        indent = "  " * len(parts)
        body.append(f"{indent}{padded} — {desc}" if desc else f"{indent}{padded} —")
        prev_parts = parts
    return body


def split_sections(text: str | None) -> list[tuple[str, list[str]]]:
    """Split a FILEMAP into (label, lines) pairs, its header dropped.

    Content before the first separator is a body from before FILEMAP had sections — this
    language's own output, superseded by what is about to be written — so it is dropped.
    """
    sections: list[tuple[str, list[str]]] = []
    for line in (text or "").split("\n"):
        match = SEPARATOR_RE.match(line)
        if match:
            sections.append((match.group(1), []))
        elif sections:
            sections[-1][1].append(line)
    return sections


def merge_onto(text: str | None, label: str, body: list[str], repo: str) -> str:
    """Write this language's section into `text`, preserving everyone else's in order.

    A further copy of this label is a duplicate left by the append bug this replaced,
    and is dropped.
    """
    sections: list[tuple[str, list[str]]] = []
    replaced = False
    for name, lines in split_sections(text):
        if name != label:
            sections.append((name, lines))
        elif not replaced:
            sections.append((label, body))
            replaced = True
    if not replaced:
        sections.append((label, body))

    out = [
        f"# FILEMAP — {repo}",
        "# Auto-generated — each language plugin owns its own section",
        "# To read a file's full header: Read(file_path, limit=20)",
    ]
    for name, lines in sections:
        filled = [i for i, line in enumerate(lines) if line.strip()]
        trimmed = lines[filled[0] : filled[-1] + 1] if filled else []
        out.extend(["", f"# ── {name} ──", "", *trimmed])
    return "\n".join(out) + "\n"


def read_text(path: Path, warnings: list[str]) -> tuple[str | None, bool]:
    """Return (text, readable); text is None when the file does not exist yet.

    Unreadable (a directory in its place, no permission) must not read as empty: merging
    onto nothing and publishing would destroy the other sections of a file never seen.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace"), True
    except FileNotFoundError:
        return None, True
    except OSError as exc:
        warnings.append(f"filemap-core: warning: {path}: cannot be read ({exc.strerror or exc})")
        return None, False


def reap_stale_tmp(outfile: Path) -> None:
    """Remove scratch files left beside FILEMAP by runs killed mid-publish.

    Only those whose recorded pid is gone, and only from inside the lock, so a live
    publisher's file is safe.
    """
    prefix = outfile.name + ".tmp."
    try:
        names = [entry.name for entry in outfile.parent.iterdir()]
    except OSError:
        return
    for name in names:
        suffix = name.removeprefix(prefix) if name.startswith(prefix) else ""
        if not suffix.isdigit() or int(suffix) == os.getpid():
            continue
        try:
            os.kill(int(suffix), 0)
        except ProcessLookupError:
            (outfile.parent / name).unlink(missing_ok=True)  # holder is gone, the file is litter
        except OSError:
            continue  # alive, or not ours to signal


def publish(outfile: Path, render: Callable[[str | None], str], warnings: list[str]) -> None:
    """Read, merge and replace FILEMAP, re-merging when another writer lands in between.

    The compare-and-swap is a second line behind the lock, for filesystems where flock
    is a no-op. `FILEMAP_CAS_DELAY` widens the window so a test can land a second writer
    in it; this script never sets it.
    """
    reap_stale_tmp(outfile)
    legacy_lock = outfile.with_name(outfile.name + ".lock")  # left by the version that locked in-tree
    if legacy_lock.is_file() and legacy_lock.stat().st_size == 0:
        legacy_lock.unlink(missing_ok=True)
    tmp = outfile.with_name(f"{outfile.name}.tmp.{os.getpid()}")
    cas_delay = float(os.environ.get("FILEMAP_CAS_DELAY") or 0)
    try:
        for _attempt in range(PUBLISH_ATTEMPTS):
            snapshot, readable = read_text(outfile, warnings)
            if not readable:
                raise PublishError(f"{outfile} exists but cannot be read; refusing to overwrite it")
            tmp.write_text(render(snapshot), encoding="utf-8")
            if cas_delay:
                time.sleep(cas_delay)
            if read_text(outfile, warnings)[0] != snapshot:
                continue  # another writer landed: re-merge onto their version
            tmp.replace(outfile)
            return
    except OSError as exc:
        raise PublishError(f"cannot write {outfile}: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    raise PublishError(f"{outfile} kept changing, giving up this run")


def publish_locked(outfile: Path, render: Callable[[str | None], str], warnings: list[str]) -> None:
    """Publish under an exclusive flock kept outside the tree.

    Keyed on the resolved path, so two symlinked routes to one checkout share a lock.
    Without a usable temp directory it publishes unlocked: the compare-and-swap still
    stands, and a rare lost section heals on the next run.
    """
    digest = hashlib.sha256(str(outfile.resolve()).encode()).hexdigest()[:16]
    lock_path = Path(tempfile.gettempdir()) / f"filemap-{digest}.lock"
    try:
        lock_handle = lock_path.open("a")
    except OSError as exc:
        warnings.append(f"filemap-core: warning: cannot open {lock_path} ({exc.strerror or exc}), publishing unlocked")
        publish(outfile, render, warnings)
        return
    with lock_handle:
        for _ in range(LOCK_ATTEMPTS):
            try:
                fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise PublishError(f"{lock_path} is held by another run, skipping this one")
        publish(outfile, render, warnings)


def index(profile: Profile, sources: list[str]) -> int:
    """Index `sources` into this language's section; the exit status."""
    try:
        index_files, listed = select(walk(sources), profile)
    except subprocess.CalledProcessError as exc:
        print(f"filemap-core: git ls-files failed: {exc.stderr.strip()}", file=sys.stderr)
        return 1
    # Nothing to index: leave FILEMAP alone rather than write an empty section. Known
    # limit: deleting a language's last file therefore leaves its old section in place.
    if not listed:
        print(f"No {profile.label} files found to index", file=sys.stderr)
        return 0

    warnings: list[str] = []
    dir_descs = {
        str(PurePosixPath(path).parent): desc for path in index_files if (desc := description(path, profile, warnings))
    }
    body = render_body([(path, description(path, profile, warnings)) for path in listed], dir_descs)
    repo = repo_name()
    OUTFILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        publish_locked(OUTFILE, lambda text: merge_onto(text, profile.label, body, repo), warnings)
    except PublishError as exc:
        # The cause first: a Stop hook surfaces only the first line of stderr.
        print(f"filemap-core: {exc}", file=sys.stderr)
        return 1
    finally:
        for line in warnings:
            print(line, file=sys.stderr)
    noun = "file" if len(listed) == 1 else "files"
    print(f"Generated {OUTFILE} ({len(listed)} {profile.label} {noun} indexed)")
    return 0


def main(argv: list[str]) -> int:
    """Resolve the tree from the hook JSON on stdin, then index it."""
    try:
        lang, sources = parse_args(argv)
    except ValueError as exc:
        print(f"filemap-core: {exc}", file=sys.stderr)
        return 1
    # stdin carries the hook JSON under Claude Code; a terminal has none to close.
    hook_input = "" if sys.stdin.isatty() else sys.stdin.read()
    os.chdir(session_cwd(hook_input))
    if git("rev-parse", "--git-dir").returncode != 0:
        print(f"filemap-core: {Path.cwd()} is not a git repository, nothing to index", file=sys.stderr)
        return 0
    return index(PROFILES[lang], sources)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
