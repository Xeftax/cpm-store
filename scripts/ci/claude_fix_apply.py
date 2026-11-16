#!/usr/bin/env python3
"""The two deterministic halves around the agent of `_claude-fix.yml`.

The agent only reads and edits files. Everything with a credential or a consequence is
here, run by the workflow, from the default branch's copy of this script, never from the
tree the agent edited:

  prepare   read the failure-tracking PR's body (the failing log, which is external data)
            into `.claude-fix/log.md` for the agent, and say which PR it is
  apply     decide whether what the agent changed may be pushed, and if so commit it with
            a fixed author and message and push it, plainly, to the check's branch; then
            comment with the agent's summary

The decision in `apply` is the boundary, not a prompt and not a tool rule: a changed path
that a pull request's CI executes as infrastructure (workflows, scripts, the agent's own
settings, a build or test configuration) refuses the whole change, with a comment and no
push. Nothing outside the allowed paths is ever staged, a symlink is never committed, and
the push is never forced, so a rewritten history cannot land.

Environment, as `_claude-fix.yml` sets it:

  BRANCH, CHECK_ID, GITHUB_REPOSITORY      which check, its branch `check/<id>`, the repo
  GH_TOKEN                                 `prepare`: the job's read token; `apply`: the App
                                           token, minted after the agent ran
  PR_NUMBER, RUN_URL                       `apply` only
  DOCKYARD_TOML                            `apply`: the default branch's dockyard.toml, fetched
                                           by the workflow; absent or empty = no check named
  CLAUDE_FIX_REMOTE                        where to push (default: the repo on github.com,
                                           authenticated by GH_TOKEN)
  GITHUB_OUTPUT                            as on a runner
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, NamedTuple

WORK_DIR = ".claude-fix"
LOG_FILE = f"{WORK_DIR}/log.md"
SUMMARY_FILE = f"{WORK_DIR}/summary.md"
FAILED_LABEL = "check-failed"
BRANCH_PATTERN = re.compile(r"^check/[a-z][a-z0-9-]{0,39}$")
# GitHub caps a body at 65536 characters.
MAX_LOG_BYTES = 60000
MAX_SUMMARY_CHARS = 4000
# A path shown in a comment: a hostile name cannot fill it.
MAX_DISPLAY_CHARS = 200
# What of a failed command's own message goes to the job log.
MAX_STDERR_CHARS = 2000
# A fix is a handful of files; more is not one.
MAX_FILES = 25
AUTHOR_NAME = "dockyard-claude-fix"
AUTHOR_EMAIL = "dockyard-claude-fix@users.noreply.github.com"
TEXT_ERRORS = "replace"

# What a pull request's CI executes as infrastructure, so a change here runs before anyone
# reads it. Refused by shape rather than by a list that goes stale: any path with a segment
# that starts with a dot (`.github/`, `.claude/`, `.git/`, `.coveragerc`, `.npmrc`, `.envrc`,
# `.husky/`, `.devcontainer/`, `.pre-commit-config.yaml`, ...); the root `scripts/`; the files
# below by name at any depth; any root `.toml`, `.cfg` or `.ini`; and every file the default
# branch's `dockyard.toml` says a check runs.
PROTECTED_DIRECTORIES = frozenset({".github", "scripts", ".claude", ".git"})
PROTECTED_NAMES = frozenset(
    {
        "conftest.py",
        "sitecustomize.py",
        "usercustomize.py",
        "pyproject.toml",
        "dockyard.toml",
        "uv.lock",
        "makefile",
        "gnumakefile",
        "justfile",
        "package.json",
        "package-lock.json",
        "setup.py",
        "setup.cfg",
        "noxfile.py",
        "tox.ini",
        "pytest.ini",
        "pytest.toml",
        "mypy.ini",
        "ruff.toml",
        "hatch_build.py",
        "claude.md",
    }
)
PROTECTED_NAME_PREFIXES = ("docker-compose", "compose.")
PROTECTED_ROOT_SUFFIXES = (".toml", ".cfg", ".ini")
# A character that would break a comment's markup or hide in a terminal.
UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f`]")


class Refusal(NamedTuple):
    """A changed path the engine will not push, and why."""

    path: str
    reason: str


class Decision(NamedTuple):
    """What may be pushed, and what stops the change from being pushed at all."""

    allowed: tuple[str, ...]
    refused: tuple[Refusal, ...]


class Config(NamedTuple):
    """The environment contract."""

    branch: str
    check_id: str
    repository: str
    token: str
    pr_number: str
    run_url: str
    remote: str
    github_output: str


def config_from(env: Mapping[str, str]) -> Config:
    """Read the contract; an empty variable is unset."""
    token = env.get("GH_TOKEN", "")
    repository = env.get("GITHUB_REPOSITORY", "")
    return Config(
        branch=env.get("BRANCH", ""),
        check_id=env.get("CHECK_ID", ""),
        repository=repository,
        token=token,
        pr_number=env.get("PR_NUMBER", ""),
        run_url=env.get("RUN_URL", ""),
        remote=env.get("CLAUDE_FIX_REMOTE") or f"https://x-access-token:{token}@github.com/{repository}.git",
        github_output=env.get("GITHUB_OUTPUT", ""),
    )


def say(message: str) -> None:
    """Print a line, flushed so it precedes the output of a git or gh call after it."""
    print(message, flush=True)


def _is_infrastructure_name(name: str) -> bool:
    """Whether a lowercased file name is one CI builds, installs or tests with, wherever it sits."""
    return (
        name in PROTECTED_NAMES
        or name == "dockerfile"
        or name.startswith(("dockerfile.", *PROTECTED_NAME_PREFIXES))
        or (name.startswith("requirements") and name.endswith(".txt"))
    )


def _shape_reason(path: str, parts: tuple[str, ...]) -> str | None:
    """Refuse what is not a plain path, or has a dot segment, or sits under a protected directory."""
    if not parts or path.startswith("/") or "\\" in path or UNSAFE_NAME.search(path):
        return "not a plain path inside the repository"
    if any(part.startswith(".") for part in parts):
        return "a dot file or directory, which tools and CI read as configuration"
    if parts[0].casefold() in PROTECTED_DIRECTORIES:
        return f"under `{parts[0]}/`, which CI runs as infrastructure"
    return None


def _real(root: Path, name: str) -> str:
    """Return `name` as it is on disk under `root`, symlinks resolved, relative to the checkout."""
    base = os.path.realpath(root)
    real = os.path.realpath(root / name)
    try:
        return str(Path(real).relative_to(base))
    except ValueError:
        return real


def _runs_a_check(path: str, check_files: frozenset[str], root: Path | None) -> bool:
    """Whether `path` is a file a check runs, by its name or, given the checkout, by where it really is.

    A tracked symlink `tools -> impl` makes an edit of `tools/run.sh` show as `impl/run.sh`, so both
    sides are resolved: comparing the names as written would let that edit through.
    """
    if path in check_files or os.path.normpath(path) in check_files:
        return True
    if root is None:
        return False
    return _real(root, path) in {_real(root, name) for name in check_files}


def protected_reason(path: str, check_files: frozenset[str] = frozenset(), root: Path | None = None) -> str | None:
    """Return why `path` may never be pushed by the engine on the agent's behalf, or None when it may."""
    parts = Path(path).parts
    shaped = _shape_reason(path, parts)
    if shaped is not None:
        return shaped
    if _runs_a_check(path, check_files, root):
        return "a file a check runs"
    if _is_infrastructure_name(parts[-1].casefold()):
        return "a file CI builds, installs or tests with"
    if len(parts) == 1 and parts[-1].casefold().endswith(PROTECTED_ROOT_SUFFIXES):
        return "a root configuration file"
    return None


def _named_files(value: object) -> list[str]:
    """Return the file a `file`, `scope`, `teardown` or `extra-hash` value names: a bare path or a table's `file`."""
    named = value.get("file") if isinstance(value, dict) else value
    return [os.path.normpath(named)] if isinstance(named, str) and named else []


def check_files(toml_text: str) -> frozenset[str]:
    """Return every file the `[check.<id>]` tables of a `dockyard.toml` say a check runs; empty text names none."""
    try:
        document = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        message = f"dockyard.toml does not parse: {exc}"
        raise ValueError(message) from exc
    tables = document.get("check", {})
    files: list[str] = []
    for table in tables.values() if isinstance(tables, dict) else []:
        if not isinstance(table, dict):
            continue
        cache = table.get("cache")
        values = [table.get(key) for key in ("file", "scope", "teardown")]
        values.append(cache.get("extra-hash") if isinstance(cache, dict) else None)
        files += [name for value in values for name in _named_files(value)]
    return frozenset(files)


def decide(paths: Sequence[str], files_run: frozenset[str] = frozenset(), root: Path | None = None) -> Decision:
    """Decide what of the agent's changed `paths` may be pushed: all of it, or nothing.

    One refused path refuses the change, since a half-applied fix is not the fix the agent
    meant. Too many files is refused as well: a fix is a handful.
    """
    unique = sorted(set(paths))
    if len(unique) > MAX_FILES:
        return Decision((), (Refusal(f"{len(unique)} files", f"more than {MAX_FILES} files is not a fix"),))
    refused = tuple(
        Refusal(path, reason) for path in unique if (reason := protected_reason(path, files_run, root)) is not None
    )
    if refused:
        return Decision((), refused)
    return Decision(tuple(unique), ())


def changed_paths(status_z: bytes) -> list[str]:
    """Return every path in a `git status --porcelain=v1 -z` listing, a rename's two sides included.

    Whatever sits under the engine's own work directory is not the agent's change.
    """
    tokens = [token.decode(errors=TEXT_ERRORS) for token in status_z.split(b"\0") if token]
    paths: list[str] = []
    expect_origin = False
    for token in tokens:
        if expect_origin:
            paths.append(token)
            expect_origin = False
            continue
        code, path = token[:2], token[3:]
        paths.append(path)
        expect_origin = "R" in code or "C" in code
    return [path for path in paths if path != WORK_DIR and not path.startswith(f"{WORK_DIR}/")]


def neutralize(text: str) -> str:
    """Drop control characters and carriage returns, and break every `@` so a name is never a mention."""
    kept = "".join(char for char in text if char in "\n\t" or (char >= " " and char != "\x7f"))
    return kept.replace("@", "@\u200b")


def fenced(text: str) -> str:
    """Return `text` in a code fence longer than any run of backticks it holds, so nothing in it is markdown."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    mark = "`" * max(3, longest + 1)
    return f"{mark}\n{text}\n{mark}"


def read_summary(root: Path) -> str:
    """Return the agent's summary as a fenced block, capped; never follows a symlink, never reads a huge file.

    The summary is text an attacker's log may have steered: an image in it would be fetched
    when the comment is viewed, a link would be clickable and a mention would notify. In a
    fence none of that happens, and the cap bounds what a hostile one can fill a PR with.
    """
    path = root / SUMMARY_FILE
    if path.is_symlink() or not path.is_file():
        return fenced("(the agent wrote no summary)")
    raw = path.read_bytes()[: MAX_SUMMARY_CHARS * 4].decode(errors=TEXT_ERRORS)
    text = neutralize(raw).strip()[:MAX_SUMMARY_CHARS]
    return fenced(text or "(the agent wrote an empty summary)")


def display(path: str) -> str:
    """Return a path safe to show in a code span: nothing that could close it or start a line of its own."""
    safe = UNSAFE_NAME.sub("?", path).replace("@", "@\u200b")
    return safe if len(safe) <= MAX_DISPLAY_CHARS else f"{safe[:MAX_DISPLAY_CHARS]}\u2026"


def staged_paths(diff_name_only_z: bytes) -> set[str]:
    """Return the paths of a `git diff --cached --name-only -z` listing."""
    return {raw.decode(errors=TEXT_ERRORS) for raw in diff_name_only_z.split(b"\0") if raw}


def push_was_rejected(stderr: bytes) -> bool:
    """Whether a failed push says the branch moved, as opposed to a permission, a network or a ref error."""
    text = stderr.decode(errors=TEXT_ERRORS).lower()
    return any(marker in text for marker in ("rejected", "non-fast-forward", "fetch first"))


def _run(env: Mapping[str, str], *argv: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    """Run one command here, its output captured as bytes; a failure is printed to the job log, and raises if `check`.

    git's and gh's own message is what says why, so it must reach the log; the App token is
    masked there by the runner, and redacted here as well.
    """
    sys.stdout.flush()
    done = subprocess.run(list(argv), env=dict(env), capture_output=True, check=False)  # noqa: S603 -- fixed argv
    if done.returncode != 0:
        message = done.stderr.decode(errors=TEXT_ERRORS)
        token = env.get("GH_TOKEN", "")
        shown = (message.replace(token, "***") if token else message)[-MAX_STDERR_CHARS:]
        say(f"{' '.join(argv[:2])} failed ({done.returncode}): {shown.strip()}")
        if check:
            raise subprocess.CalledProcessError(done.returncode, list(argv), done.stdout, done.stderr)
    return done


def _write_output(cfg: Config, name: str, value: str) -> None:
    if cfg.github_output:
        with Path(cfg.github_output).open("a", encoding="utf-8") as out:
            out.write(f"{name}={value}\n")


def prepare(env: Mapping[str, str], root: Path) -> int:
    """Write the tracking PR's body for the agent and name the PR; nothing is written when there is no PR."""
    cfg = config_from(env)
    if not BRANCH_PATTERN.match(cfg.branch):
        say(f"::error::{cfg.branch!r} is not a check branch")
        return 1
    listing = _run(env, "gh", "pr", "list", "--head", cfg.branch, "--state", "open", "--json", "number,body,labels")
    prs = json.loads(listing.stdout.decode(errors=TEXT_ERRORS) or "[]")
    tracked = next((pr for pr in prs if FAILED_LABEL in {label["name"] for label in pr["labels"]}), None)
    if tracked is None:
        say(f"::notice::no open `{FAILED_LABEL}` pull request from {cfg.branch}: nothing to propose a fix on")
        _write_output(cfg, "pr", "")
        return 0
    (root / WORK_DIR).mkdir(exist_ok=True)
    (root / LOG_FILE).write_text(str(tracked["body"])[:MAX_LOG_BYTES], encoding="utf-8")
    # Not the agent's change: git must not see the work directory at all.
    exclude = root / ".git" / "info" / "exclude"
    with exclude.open("a", encoding="utf-8") as out:
        out.write(f"\n{WORK_DIR}/\n")
    _write_output(cfg, "pr", str(tracked["number"]))
    return 0


def _post(env: Mapping[str, str], cfg: Config, body: str) -> bool:
    """Post `body` on the PR from a file; return whether it landed."""
    marker = f"<!-- dockyard-claude-fix:{cfg.check_id} -->"
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8") as handle:
        handle.write(f"{marker}\n{body}\n")
        handle.flush()
        try:
            _run(env, "gh", "pr", "comment", cfg.pr_number, "--body-file", handle.name)
        except subprocess.CalledProcessError:
            return False
    return True


def _comment(env: Mapping[str, str], cfg: Config, body: str) -> None:
    """Comment on the PR, and when that fails say so shortly instead; a comment never changes the verdict."""
    if _post(env, cfg, body):
        return
    say("::warning::the comment could not be posted in full")
    fallback = f"The fix job finished but its comment could not be posted in full: see [the run]({cfg.run_url})."
    if not _post(env, cfg, fallback):
        say("::warning::could not post the comment")


def _refusals(root: Path, decision: Decision) -> Decision:
    """Add a refusal for a symlink among the allowed paths: its target is not something to commit."""
    links = tuple(Refusal(path, "a symlink") for path in decision.allowed if (root / path).is_symlink())
    return Decision((), decision.refused + links) if links else decision


class StagedMoreError(Exception):
    """The index holds something other than what was allowed."""


def _commit(env: Mapping[str, str], cfg: Config, allowed: Sequence[str]) -> None:
    """Stage exactly `allowed`, as literal paths, verify that is all the index holds, and commit it.

    Git can stage more than a pathspec names: writing into an empty gitlink directory turns the
    submodule entry into a deletion. So the staged set must equal the allowed one, or nothing is
    committed and the index is cleared.
    """
    _run(env, "git", "--literal-pathspecs", "add", "-A", "--", *allowed)
    staged = staged_paths(_run(env, "git", "diff", "--cached", "--name-only", "-z", "--no-renames").stdout)
    if staged != set(allowed):
        _run(env, "git", "reset", "-q")
        raise StagedMoreError
    identity = ("-c", f"user.name={AUTHOR_NAME}", "-c", f"user.email={AUTHOR_EMAIL}")
    hardening = ("-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false")
    message = f"fix: propose a fix for the {cfg.check_id} check"
    trailer = f"Dockyard-Claude-Fix: {cfg.check_id}"
    _run(env, "git", *identity, *hardening, "commit", "-q", "--no-verify", "-m", message, "-m", trailer)


def _push(env: Mapping[str, str], cfg: Config) -> Literal["pushed", "moved", "failed"]:
    """Push HEAD plainly, never forced; say whether it landed, the branch moved, or something else broke."""
    pushed = _run(env, "git", "push", cfg.remote, f"HEAD:refs/heads/{cfg.branch}", check=False)
    if pushed.returncode == 0:
        return "pushed"
    return "moved" if push_was_rejected(pushed.stderr) else "failed"


def _files_run(env: Mapping[str, str]) -> frozenset[str]:
    """Read the files the default branch's `dockyard.toml` says a check runs; none when it is absent or empty."""
    path = Path(env.get("DOCKYARD_TOML", ""))
    if not path.is_file():
        return frozenset()
    return check_files(path.read_text(encoding="utf-8", errors=TEXT_ERRORS))


def _propose(
    env: Mapping[str, str], root: Path, cfg: Config, paths: list[str], files_run: frozenset[str]
) -> tuple[str, int]:
    """Decide, commit and push the agent's `paths`; return what to say above its summary, and the exit status."""
    decision = _refusals(root, decide(paths, files_run, root))
    if decision.refused:
        listing = "\n".join(f"- `{display(item.path)}`: {item.reason}" for item in decision.refused)
        return f"The agent's change was not pushed:\n\n{listing}", 0
    try:
        _commit(env, cfg, decision.allowed)
    except StagedMoreError:
        return "The agent's change staged more than it was allowed to (a submodule, say): nothing was pushed.", 0
    except subprocess.CalledProcessError:
        return "The agent's change could not be committed, so nothing was pushed (see the job log).", 1
    outcome = _push(env, cfg)
    if outcome == "moved":
        return f"The agent's change could not be pushed to `{cfg.branch}`: it moved.", 1
    if outcome == "failed":
        return f"The agent's change could not be pushed to `{cfg.branch}` (see the job log).", 1
    files = "\n".join(f"- `{path}`" for path in decision.allowed)
    return f"A fix is proposed on `{cfg.branch}` ([run]({cfg.run_url})):\n\n{files}", 0


def apply(env: Mapping[str, str], root: Path) -> int:
    """Decide what the agent changed, push it if it may be, and comment with its summary; return the exit status."""
    cfg = config_from(env)
    if not BRANCH_PATTERN.match(cfg.branch) or not cfg.pr_number.isdigit():
        say("::error::apply needs a check branch and a pull request number")
        return 1
    # The token the agent's own step left in the remote is not this one, and must not outlive it.
    _run(env, "git", "remote", "set-url", "origin", f"https://github.com/{cfg.repository}.git")
    summary = read_summary(root)
    try:
        files_run = _files_run(env)
    except ValueError:
        _comment(env, cfg, f"Nothing was pushed: the default branch's `dockyard.toml` could not be read.\n\n{summary}")
        return 1
    paths = changed_paths(_run(env, "git", "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout)
    said, status = ("No fix proposed.", 0) if not paths else _propose(env, root, cfg, paths, files_run)
    _comment(env, cfg, f"{said}\n\n{summary}")
    return status


def main(argv: Sequence[str], env: Mapping[str, str] | None = None) -> int:
    """Run `prepare` or `apply` from the current checkout."""
    environment = os.environ if env is None else env
    commands = {"prepare": prepare, "apply": apply}
    if len(argv) != 1 or argv[0] not in commands:
        say("usage: claude_fix_apply.py prepare|apply")
        return 2
    return commands[argv[0]](environment, Path.cwd())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
