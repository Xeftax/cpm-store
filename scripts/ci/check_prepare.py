#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Decide, before a check runs, whether it has to: its scope, its recorded verdict, its secrets.

Run by `_check-prepare.yml`, the job `ci.yml` puts in front of a check that declares a
`scope`, a `cache`, or whose `file` is a workflow under `.github/workflows/` (`prepare`),
and by `_check.yml` around a check that passed: to put a workflow's handed-over files into
the checkout (`lay-changes`), then to name the marker that records the verdict (`key`).
Everything arrives through the environment and leaves through $GITHUB_OUTPUT.

`scope-glob <glob>...` is the classifier a `scope` written as a list of globs runs: the
changed paths on stdin, `all` or `none` on stdout.

  prepare
    CHECK_ID, EVENT            the check and `github.event_name`
    CHECK_ENV                  JSON object, name to value: the check's `var:` entries, exported to the
                               classifier and the hash command (a literal is already in their command line)
    BASE_SHA                   the diff base for the event; blank = there is no diff to take
    SCOPE_CMD                  the classifier command; blank = the check declares no scope. It gets the
                               changed paths on stdin and, in BASE_SHA, the MERGE-BASE of the diff base and
                               HEAD: the commit those paths are measured from (the diff is `BASE...HEAD`,
                               three dots), so `git show "$BASE_SHA:<file>"` is the file as this branch
                               found it, and a classifier can judge a file by what changed in it. This
                               is not the base branch's tip, which a push to it may have moved since.
    DISPATCH_SCOPE             the scope a manual run chose; on a dispatch it replaces the classifier
    CACHE                      `true` when the check declares a cache
    CACHE_EXTRA_HASH           the command whose stdout joins the verdict key
    CACHE_EXCLUDE              newline-separated git pathspec globs left out of the tree hash
    CACHE_TTL_DAYS             freshness window of a marker (default 7)
    REQUIRES_SECRETS           `true` for a workflow check (handed the `secret:` entries of its `env`)
    PR_FROM_FORK, ACTOR, PR_AUTHOR   who the pull request comes from
    DEFAULT_BRANCH, HEAD_BRANCH      the branches whose markers are believed (see below)
    GH_TOKEN, GITHUB_REPOSITORY      to list the markers (`actions: read` is enough)
  key
    CHECK_ID, SCOPE, CACHE_EXTRA_HASH, CACHE_EXCLUDE, CACHE_TTL_DAYS, RUNNER_TEMP, CHECK_ENV
    CHECK_PATHS                what the check may change; a change left over them records nothing
  lay-changes
    CHECK_CHANGES_DIR, CHECK_PATHS   a workflow check's handed-over files, and where they may go
  export-env
    CHECK_ENV                  JSON object, name to value: the check's `var:` entries
    CHECK_SECRET_ENV           JSON object, name to value: its `secret:` entries
    CHECK_SECRET_NAMES         JSON object, name to secret name: the `secret:` entries of a check with an
                               environment, looked up in CHECK_SECRETS
    CHECK_SECRETS              JSON object, secret name to value: that environment's DOCKYARD_CHECK_SECRETS
    CHECK_DISPATCH             JSON object, option name to the choice a manual run gave it
    RUNNER_TEMP                where the `check.env` file the run step sources is written

`prepare` writes `scope` (`none`, `all`, a comma-separated list, or blank when the check has no
scope), `skip` (`true` when the check passes without running: nothing in scope, or this content
already passed), `skip-reason`, `unavailable` (a reason when the check needs secrets this run
cannot have, blank otherwise) and `run` (`true` when the check still has to run).

Three rules, each one a way "could not decide" must never read as "nothing to do":

- A classifier that fails, prints nothing, prints something that is not a scope, or is given
  an empty diff, answers `all`. The worst this costs is a run that was not needed.
- A recorded verdict is a hit only when it is found, fresh, the key matches and the run that
  recorded it is one this repo trusts and in which the check's job succeeded; any error on the
  way, `gh` included, is a miss. A
  scheduled or dispatched run never reads the cache: it exists to look again at what a verdict
  says is fine.
- Any pull request branch of the repo can upload an artifact of any name, so a marker counts
  only when its run is from this repo (not a fork) and on the default branch (event `push` or
  `merge_group`), a merge-queue branch (`gh-readonly-queue/...`, event `merge_group`) or the
  very branch this run is on. A marker is also named
  after its check: two checks on one tree and scope must not share a verdict. The tree hash
  covers this repo only: a check with a second repository (`source-repo`) cannot declare a
  cache, since that repository's content is not in the key.
- The classifier and the hash command run with the run's tokens removed from their
  environment: on a pull request they are the PR's own code.

`prepare` always exits 0 with outputs written; a crash is the only way to a non-zero exit,
and the job then fails, which the gate reads as a failed check.
"""

import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ALL = "all"
NONE = "none"
# What a classifier may print: one of the two words, or a comma-separated list of tokens.
SCOPE_SHAPE = re.compile(r"^(?:[A-Za-z0-9_./-]+)(?:,[A-Za-z0-9_./-]+)*$")
# Events that diff against a base. A schedule or a dispatch has none, and runs the whole check.
DIFFED_EVENTS = frozenset({"pull_request", "merge_group", "push"})
# Events that never consult the cache: they exist to look again.
UNCACHED_EVENTS = frozenset({"schedule", "workflow_dispatch"})
DEFAULT_TTL_DAYS = 7
DEPENDABOT = "dependabot[bot]"
# A run of the merge queue holds the candidate tree, and only GitHub names its branch.
QUEUE_BRANCH_PREFIX = "gh-readonly-queue/"
# How many markers of one name the lookup reads: they are few, but the newest may be untrusted.
MARKERS_PER_LOOKUP = 100
# Variables a command run from here must not see: on a pull request it is the PR's own code.
TOKEN_VARIABLES = ("GH_TOKEN", "GITHUB_TOKEN", "APP_TOKEN")


# A variable or a secret is exported to code that runs in CI and its value is not in the
# reviewed diff, so a name that steers the runner or an interpreter is refused. The same list
# as `dockyard.checks.RESERVED_ENV_NAMES` (a test holds them equal): this script is copied
# into the caller's run and cannot import it.
RESERVED_ENV_NAMES = (
    "PATH",
    "HOME",
    "SHELL",
    "IFS",
    "ENV",
    "GITHUB_*",
    "RUNNER_*",
    "ACTIONS_*",
    "INPUT_*",
    "LD_*",
    "DYLD_*",
    "PYTHON*",
    "NODE_*",
    "GIT_*",
    "BASH_*",
    "PROMPT_COMMAND",
    "PS4",
    "CDPATH",
    "RUBYOPT",
    "RUBYLIB",
    "PERL5OPT",
    "PERL5LIB",
    "JAVA_TOOL_OPTIONS",
    "JDK_JAVA_OPTIONS",
)
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
DISPATCH_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
ENV_FILE = "check.env"


@dataclass(frozen=True)
class Prepared:
    """What `prepare` decided."""

    scope: str
    run: bool
    skip: bool = False
    skip_reason: str = ""
    unavailable: str = ""


def say(message: str) -> None:
    """Print a workflow command or a line of log, flushed so it keeps its place."""
    print(message, flush=True)


def clean_env(environ: Mapping[str, str]) -> dict[str, str]:
    """Return `environ` without the run's tokens."""
    return {name: value for name, value in environ.items() if name not in TOKEN_VARIABLES}


def command_env(environ: Mapping[str, str]) -> dict[str, str]:
    """Return what the classifier and the hash command run with: no tokens, plus the check's variables.

    The variables come from `CHECK_ENV` and are checked as `export-env` checks them; an unset
    or empty one is left out, as there, so the command's own default applies.
    """
    declared = read_env_object(environ.get("CHECK_ENV", ""), "CHECK_ENV")
    for name in declared:
        check_env_name(name)
    return {**clean_env(environ), **{name: value for name, value in declared.items() if value}}


def run(
    argv: Sequence[str], environ: Mapping[str, str], *, stdin: str | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run `argv`, capturing stdout; never raises on a non-zero exit."""
    return subprocess.run(  # noqa: S603 -- fixed argv or `bash -c` on a command the repo declared
        list(argv),
        env=dict(environ),
        input=None if stdin is None else stdin.encode(),
        capture_output=True,
        check=False,
    )


# ------------------------------------------------------------------------------- scope


def changed_paths(fork_point: str, environ: Mapping[str, str]) -> list[str] | None:
    """Return the paths changed between `fork_point` and HEAD, or None when git cannot say."""
    done = run(["git", "-c", "core.quotePath=false", "diff", "--name-only", fork_point, "HEAD"], environ)
    if done.returncode != 0:
        say(f"::warning::scope: 'git diff {fork_point} HEAD' failed — falling back to the whole check")
        return None
    return [line for line in done.stdout.decode(errors="replace").splitlines() if line]


def normalise_scope(printed: str) -> str | None:
    """Return the scope a classifier printed, or None when it is not a scope.

    A list holding `all` is `all`; one holding `none` beside other tokens contradicts itself,
    and is not a scope.
    """
    text = printed.strip()
    if not text or "\n" in text or not SCOPE_SHAPE.match(text):
        return None
    tokens = text.split(",")
    if ALL in tokens:
        return ALL
    if NONE in tokens and len(tokens) > 1:
        return None
    return text


def chosen_scope(event: str, environ: Mapping[str, str]) -> str:
    """Return the scope a manual run chose ('' when it chose none, or this is not a manual run).

    A person asked for exactly that, and a classifier reads a diff a dispatch does not have.
    Only a dispatch is believed; the same variable on any other event is ignored.

    A choice that is not a scope is `all`: the whole check is the cheap mistake.
    """
    chosen = environ.get("DISPATCH_SCOPE", "").strip()
    if event != "workflow_dispatch" or not chosen:
        return ""
    scope = normalise_scope(chosen)
    if scope is None:
        say(f"::warning::scope: {chosen!r} is not a scope — the whole check")
        return ALL
    say(f"scope: {scope} (chosen for this manual run)")
    return scope


def merge_base(base_sha: str, environ: Mapping[str, str]) -> str | None:
    """Return the commit `base_sha...HEAD` is measured from, or None when git cannot say."""
    done = run(["git", "merge-base", base_sha, "HEAD"], environ)
    fork_point = done.stdout.decode(errors="replace").strip() if done.returncode == 0 else ""
    if not fork_point:
        say(f"::warning::scope: no merge-base between {base_sha} and HEAD — falling back to the whole check")
        return None
    return fork_point


def compute_scope(scope_cmd: str, event: str, base_sha: str, environ: Mapping[str, str]) -> str:
    """Classify the diff with the repo's own command; `all` whenever it cannot be known."""
    if event not in DIFFED_EVENTS or not base_sha:
        say(f"scope: {event or 'this run'} has no diff to classify — the whole check")
        return ALL
    # One base for both: the paths on stdin and BASE_SHA are measured from the same commit,
    # the one a three-dot diff would use, and a missing merge-base is the one failure.
    fork_point = merge_base(base_sha, environ)
    paths = None if fork_point is None else changed_paths(fork_point, environ)
    if fork_point is None or paths is None:
        return ALL
    if not paths:
        # More often a broken base than an empty change, and a genuine repeat is what the
        # verdict cache is for: running once too often is the cheap mistake.
        say("scope: the diff is empty — taking the whole check rather than guessing nothing changed")
        return ALL
    classifier_env = {**command_env(environ), "BASE_SHA": fork_point}
    done = run(["bash", "-c", scope_cmd], classifier_env, stdin="\n".join(paths) + "\n")
    if done.returncode != 0:
        say(f"::warning::scope: '{scope_cmd}' exited {done.returncode} — falling back to the whole check")
        return ALL
    scope = normalise_scope(done.stdout.decode(errors="replace"))
    if scope is None:
        say(f"::warning::scope: '{scope_cmd}' printed no scope — falling back to the whole check")
        return ALL
    say(f"scope: {scope}")
    return scope


# ------------------------------------------------------------------------------- cache


def tree_listing(exclude: Sequence[str], environ: Mapping[str, str]) -> bytes:
    """Return `git ls-tree -r HEAD`, minus the tracked files any `exclude` glob matches.

    The listing the cache key hashes, so a tree that did not change keeps its key.
    Without a glob it is the plain listing; git itself evaluates the globs.
    """
    plain = ["git", "ls-tree", "-r", "HEAD"]
    if not exclude:
        return run(plain, environ).stdout
    specs = [f":(glob){pattern}" for pattern in exclude]
    quiet = ["git", "-c", "core.quotePath=false"]
    excluded = set(run([*quiet, "ls-files", "--", *specs], environ).stdout.decode(errors="replace").splitlines())
    listing = run([*quiet, "ls-tree", "-r", "HEAD"], environ).stdout.decode(errors="replace")
    kept = [line for line in listing.splitlines() if line.partition("\t")[2] not in excluded]
    return "".join(f"{line}\n" for line in kept).encode()


def verdict_name(
    check_id: str, scope: str, extra_hash_cmd: str, exclude: Sequence[str], environ: Mapping[str, str]
) -> str | None:
    """Return the marker name for this check, content and scope, or None when the key cannot be computed.

    The check id leads the key: the name is the verdict, so without it a check that passed
    would skip any other check run on the same tree and scope. A blank id gives a key with no owner.
    """
    tree = hashlib.sha256(tree_listing(exclude, environ)).hexdigest()
    slug = scope.replace("/", "-").replace(",", "_")
    extra = "none"
    if extra_hash_cmd:
        done = run(["bash", "-c", extra_hash_cmd], command_env(environ))
        if done.returncode != 0:
            say(f"::warning::cache: '{extra_hash_cmd}' exited {done.returncode} — no verdict key")
            return None
        extra = hashlib.sha256(done.stdout).hexdigest()
    owner = f"{check_id}-" if check_id else ""
    return f"verdict-{owner}{tree}-{slug}-{extra}"


def is_fresh(created_at: str, ttl_days: int, now: datetime | None = None) -> bool:
    """Whether a marker created at `created_at` (ISO 8601) is inside the freshness window."""
    stamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return ((now or datetime.now(UTC)) - stamp).days < ttl_days


def run_event(run_id: object, environ: Mapping[str, str]) -> str:
    """Return the event of workflow run `run_id`, or '' when it cannot be read (a miss)."""
    repository = environ.get("GITHUB_REPOSITORY", "")
    if not repository or not isinstance(run_id, int) or isinstance(run_id, bool):
        return ""
    path = f"repos/{repository}/actions/runs/{run_id}"
    done = run(["gh", "api", "--method", "GET", path, "--jq", ".event"], environ)
    return done.stdout.decode(errors="replace").strip() if done.returncode == 0 else ""


def run_passed(run_id: object, check_id: str, environ: Mapping[str, str]) -> bool:
    """Whether the job of check `check_id` in workflow run `run_id` concluded `success`.

    The marker is an artifact whose name alone says "passed", and it is uploaded before the job
    ends, so the run that wrote it has to say it did pass. The job is the check's own: named
    `<id>` or, through a caller, `<caller> / <id>`. Anything unreadable, still running, missing
    or not a success is a miss.
    """
    repository = environ.get("GITHUB_REPOSITORY", "")
    if not repository or not check_id or not isinstance(run_id, int) or isinstance(run_id, bool):
        return False
    path = f"repos/{repository}/actions/runs/{run_id}/jobs"
    jobs = ".jobs[] | [.name, .conclusion] | @tsv"
    done = run(["gh", "api", "--method", "GET", "--paginate", path, "--jq", jobs], environ)
    if done.returncode != 0:
        return False
    verdicts = []
    for line in done.stdout.decode(errors="replace").splitlines():
        name, _, conclusion = line.partition("\t")
        if name == check_id or name.endswith(f" / {check_id}"):
            verdicts.append(conclusion)
    return bool(verdicts) and all(verdict == "success" for verdict in verdicts)


def is_trusted_marker(artifact: object, environ: Mapping[str, str]) -> bool:
    """Whether the run that recorded `artifact` is one whose verdict this repo believes.

    A same-repo pull request branch can upload an artifact of any name, for a tree it
    predicts, and can be named like the default branch or the queue's, so a branch name
    alone proves nothing. Believed: a run of this repo (a fork's runs are not, whatever
    their branch is called) that is
    - on the branch this run is on (its author could already skip their own check);
    - on the default branch, when its event is `push` or `merge_group`;
    - on a merge-queue branch, when its event is `merge_group`, which only GitHub starts.
    And in every case the check's job in that run must have succeeded (`run_passed`): a marker
    is evidence of a pass only if the run that wrote it passed.
    """
    origin = artifact.get("workflow_run") if isinstance(artifact, dict) else None
    if not isinstance(origin, dict):
        return False
    head_repository = origin.get("head_repository_id")
    branch = origin.get("head_branch")
    from_this_repository = head_repository is not None and head_repository == origin.get("repository_id")
    if not from_this_repository or not isinstance(branch, str) or not branch:
        return False
    if not run_passed(origin.get("id"), environ.get("CHECK_ID", ""), environ):
        return False
    default = environ.get("DEFAULT_BRANCH", "")
    if branch == environ.get("HEAD_BRANCH", "") and branch != default:
        return True
    if branch == default:
        return run_event(origin.get("id"), environ) in {"push", "merge_group"}
    return branch.startswith(QUEUE_BRANCH_PREFIX) and run_event(origin.get("id"), environ) == "merge_group"


def recorded_verdict(name: str, ttl_days: int, environ: Mapping[str, str]) -> bool:
    """Whether a fresh marker called `name`, from a trusted run, exists; any error on the way is a miss."""
    repository = environ.get("GITHUB_REPOSITORY", "")
    if not repository:
        return False
    try:
        done = run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                f"repos/{repository}/actions/artifacts",
                "-f",
                f"name={name}",
                "-F",
                f"per_page={MARKERS_PER_LOOKUP}",
            ],
            environ,
        )
        if done.returncode != 0:
            return False
        listing = json.loads(done.stdout.decode())
        artifacts = listing.get("artifacts") if isinstance(listing, dict) else None
        if not isinstance(artifacts, list):
            return False
        return any(
            isinstance(artifact, dict)
            and artifact.get("expired") is False
            and isinstance(artifact.get("created_at"), str)
            and is_fresh(artifact["created_at"], ttl_days)
            and is_trusted_marker(artifact, environ)
            for artifact in artifacts
        )
    except (OSError, ValueError):
        return False


# ----------------------------------------------------------------------------- secrets


def secretless_reason(environ: Mapping[str, str]) -> str:
    """Return why this run holds no secrets, or '' when it does.

    A pull request from a fork gets none, and nor does one Dependabot opened (it has its own
    secret store): a check that needs secrets cannot run there, and is not skipped silently.
    """
    if environ.get("EVENT") != "pull_request":
        return ""
    if environ.get("PR_FROM_FORK") == "true":
        return "this pull request comes from a fork, which GitHub gives no secrets"
    if DEPENDABOT in (environ.get("ACTOR", ""), environ.get("PR_AUTHOR", "")):
        return "this pull request is Dependabot's, which GitHub gives no repository secrets"
    return ""


# --------------------------------------------------------------------------------- flow


def ttl_days(environ: Mapping[str, str]) -> int:
    """Read the freshness window, defaulting when it is blank or not a number."""
    try:
        return int(environ.get("CACHE_TTL_DAYS") or DEFAULT_TTL_DAYS)
    except ValueError:
        return DEFAULT_TTL_DAYS


def exclusions(environ: Mapping[str, str]) -> list[str]:
    """Read the tree exclusions: one glob a line, blanks dropped."""
    return [line.strip() for line in environ.get("CACHE_EXCLUDE", "").splitlines() if line.strip()]


def prepare(environ: Mapping[str, str]) -> Prepared:
    """Decide whether the check runs, in the order a cheap answer comes first."""
    event = environ.get("EVENT", "")
    scope_cmd = environ.get("SCOPE_CMD", "")
    scope = ""
    if scope_cmd:
        scope = chosen_scope(event, environ) or compute_scope(scope_cmd, event, environ.get("BASE_SHA", ""), environ)
    if scope == NONE:
        return Prepared(scope, run=False, skip=True, skip_reason="nothing in this diff is in the check's scope")
    if environ.get("CACHE") == "true" and event not in UNCACHED_EVENTS:
        extra = environ.get("CACHE_EXTRA_HASH", "")
        name = verdict_name(environ.get("CHECK_ID", ""), scope or ALL, extra, exclusions(environ), environ)
        if name is not None and recorded_verdict(name, ttl_days(environ), environ):
            say(f"cache: {name} is recorded and fresh")
            return Prepared(
                scope, run=False, skip=True, skip_reason="this exact content already passed (recorded verdict)"
            )
        say(f"cache: {name or 'no key'} — miss")
    if environ.get("REQUIRES_SECRETS") == "true":
        reason = secretless_reason(environ)
        if reason:
            say(f"::notice::{environ.get('CHECK_ID', 'check')} needs secrets and cannot run: {reason}")
            return Prepared(scope, run=False, unavailable=reason)
    return Prepared(scope, run=True)


def left_a_change(environ: Mapping[str, str]) -> bool:
    """Whether the check left anything to commit over its `paths`; git failing counts as yes.

    A verdict recorded over a tree whose own output is out of date would be trusted by a
    re-run that still has the drift. A new untracked file counts, as it does for the mode.
    """
    paths = [line for line in environ.get("CHECK_PATHS", "").splitlines() if line]
    if not paths:
        return False
    done = run(["git", "status", "--porcelain", "--untracked-files=all", "--", *paths], environ)
    return done.returncode != 0 or bool(done.stdout.strip())


def record_key(environ: Mapping[str, str]) -> dict[str, str]:
    """Name the marker to record for the content as it is now, and write the file that carries it.

    Called after the check passed and before anything switches branches: the extra hash reads
    what the check just produced, which is what a later run must find unchanged. Nothing is
    recorded when the check left a change over its paths: that run is not a pass of this tree.
    """
    if left_a_change(environ):
        say("cache: the check left a change over its paths — no verdict recorded")
        return {"record": "false"}
    extra = environ.get("CACHE_EXTRA_HASH", "")
    name = verdict_name(environ.get("CHECK_ID", ""), environ.get("SCOPE") or ALL, extra, exclusions(environ), environ)
    if name is None:
        return {"record": "false"}
    marker = Path(environ.get("RUNNER_TEMP", ".")) / "check-verdict-marker.txt"
    marker.write_text("This file's content is never read: the artifact name is the marker.\n")
    # Kept just past the window a lookup trusts, so retention never outlives the evidence.
    return {"record": "true", "name": name, "path": str(marker), "retention-days": str(ttl_days(environ) + 1)}


# ----------------------------------------------------------------------- declared env


class EnvError(ValueError):
    """The declared environment cannot be exported as written; the run must not start."""


def read_env_object(raw: str, label: str) -> dict[str, str | None]:
    """Parse a JSON object of name to value; an empty string is an empty object."""
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as error:
        message = f"{label} is not JSON: {error}"
        raise EnvError(message) from error
    if not isinstance(parsed, dict) or not all(v is None or isinstance(v, str) for v in parsed.values()):
        message = f"{label} must be a JSON object of strings"
        raise EnvError(message)
    return parsed


def check_env_name(name: str) -> None:
    """Refuse a name that is not UPPER_SNAKE or that steers the runner or an interpreter."""
    if not ENV_NAME.match(name):
        message = f"'{name}' is not an UPPER_SNAKE name"
        raise EnvError(message)
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in RESERVED_ENV_NAMES):
        message = f"{name} steers the runner or an interpreter and is refused"
        raise EnvError(message)


def dispatch_exports(dispatch: Mapping[str, str | None]) -> list[str]:
    """Return one export per option of a manual run; an option it was not given is exported empty (the default)."""
    lines: list[str] = []
    for option, choice in dispatch.items():
        if not DISPATCH_NAME.match(option):
            message = f"dispatch option '{option}' is not lower kebab-case"
            raise EnvError(message)
        lines.append(f"export CHECK_DISPATCH_{option.upper().replace('-', '_')}={shlex.quote(choice or '')}\n")
    return lines


# The one secret an environment holds for the checks that declare it: a JSON object, secret
# name to value. `_check.yml` declares it by this name because GitHub hands a called workflow
# an environment's secret only under a name the workflow declares.
ENVIRONMENT_SECRETS = "DOCKYARD_CHECK_SECRETS"


def named_secrets(environ: Mapping[str, str]) -> dict[str, str | None]:
    """Pick the secrets CHECK_SECRET_NAMES names out of the environment's JSON, keyed by their exported names."""
    names = read_env_object(environ.get("CHECK_SECRET_NAMES", ""), "CHECK_SECRET_NAMES")
    if not names:
        return {}
    available = read_env_object(environ.get("CHECK_SECRETS", ""), ENVIRONMENT_SECRETS)
    picked: dict[str, str | None] = {}
    for name, secret in names.items():
        if not secret or not ENV_NAME.match(secret):
            message = f"{name} names the secret '{secret}', which is not an UPPER_SNAKE secret a check may read"
            raise EnvError(message)
        picked[name] = available.get(secret)
    return picked


def export_env(environ: Mapping[str, str]) -> dict[str, str]:
    """Write the file the run step sources, and return `unavailable` when a secret it names is not set.

    A variable that is unset is a warning (the script may have a default); a secret that is
    unset means the check cannot be verified, which is not the same as passing. Secret
    values are masked, each line, because a mask matches line by line.
    """
    variables = read_env_object(environ.get("CHECK_ENV", ""), "CHECK_ENV")
    dispatch = read_env_object(environ.get("CHECK_DISPATCH", ""), "CHECK_DISPATCH")
    secrets = read_env_object(environ.get("CHECK_SECRET_ENV", ""), "CHECK_SECRET_ENV") | named_secrets(environ)
    lines: list[str] = []
    missing: list[str] = []
    lines.extend(dispatch_exports(dispatch))
    for is_secret, declared in ((False, variables), (True, secrets)):
        for name, value in declared.items():
            check_env_name(name)
            if not value:
                if is_secret:
                    missing.append(name)
                else:
                    say(f"::warning::the repository variable behind {name} is not set")
                continue
            if is_secret:
                for line in value.splitlines():
                    if line:
                        say(f"::add-mask::{line}")
            lines.append(f"export {name}={shlex.quote(value)}\n")
    if missing:
        where = (
            f"the {ENVIRONMENT_SECRETS} secret of the check's environment"
            if environ.get("CHECK_SECRET_NAMES")
            else "this repository"
        )
        return {"unavailable": f"the secret behind {', '.join(missing)} is not set in {where}"}
    target = Path(environ.get("RUNNER_TEMP", ".")) / ENV_FILE
    target.write_text("".join(lines))
    target.chmod(0o600)
    return {"unavailable": ""}


# ---------------------------------------------------------------------- handed-over files


def under_paths(relative: str, paths: Sequence[str]) -> bool:
    """Whether `relative` is one of `paths`, below one that is a directory, or matched by one that is a glob."""
    return any(
        relative == path or relative.startswith(path.rstrip("/") + "/") or fnmatch.fnmatchcase(relative, path)
        for path in paths
    )


def lay_changes(source: Path, paths: Sequence[str], root: Path) -> list[str]:
    """Copy a workflow's handed-over files into `root`, and return what was refused, one line each.

    The files come out of an artifact the repo's own workflow uploaded, and the bot may go on
    to commit them, so each is checked before it is written: a plain file, below one of the
    check's paths, and reaching `root` through no symlink. Laid here, before the verdict key
    and the mode are worked out, so both see the tree as the check left it.
    """
    refused: list[str] = []
    root = root.resolve()
    for file in sorted(source.rglob("*")):
        if file.is_dir() and not file.is_symlink():
            continue
        relative = file.relative_to(source).as_posix()
        destination = (root / relative).resolve()
        if file.is_symlink() or not file.is_file():
            refused.append(f"{relative}: not a plain file")
        elif not under_paths(relative, paths):
            refused.append(f"{relative}: outside the check's paths")
        elif root not in destination.parents:
            refused.append(f"{relative}: it leaves the checkout")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, destination)
    return refused


def write_outputs(environ: Mapping[str, str], values: Mapping[str, str]) -> None:
    """Append `values` to $GITHUB_OUTPUT when it is set, and echo them otherwise."""
    target = environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{name}={value}\n" for name, value in values.items())
    if target:
        with Path(target).open("a", encoding="utf-8") as out:
            out.write(lines)
    else:
        sys.stdout.write(lines)


def scope_glob(paths: Sequence[str], globs: Sequence[str]) -> str:
    """Return `all` when a changed path matches one of `globs`, else `none`: a glob-list `scope`'s classifier.

    `PurePosixPath.full_match`, so `*` stays inside a segment and `**` crosses them, as in a
    workflow's `paths:` filter. No match is `none`, which passes the check without running it;
    an empty diff never reaches here, `prepare` reads it as the whole check first.
    """
    matched = any(PurePosixPath(path).full_match(glob) for path in paths if path for glob in globs)
    return "all" if matched else "none"


def main(argv: Sequence[str], environ: Mapping[str, str] | None = None) -> int:
    """Run one subcommand against the environment; return the exit status."""
    if argv[:1] == ["scope-glob"] and len(argv) > 1:
        sys.stdout.write(scope_glob(sys.stdin.read().splitlines(), argv[1:]) + "\n")
        return 0
    return _engine_command(argv, os.environ if environ is None else environ)


def _engine_command(argv: Sequence[str], env: Mapping[str, str]) -> int:
    """Run one of the subcommands the engine's workflows call, reading their environment."""
    if len(argv) != 1 or argv[0] not in {"prepare", "key", "lay-changes", "export-env"}:
        print("usage: check_prepare.py prepare|key|lay-changes|export-env|scope-glob <glob>...", file=sys.stderr)
        return 2
    if argv[0] == "export-env":
        try:
            write_outputs(env, export_env(env))
        except EnvError as error:
            say(f"::error::the declared environment: {error}")
            return 1
        return 0
    if argv[0] == "lay-changes":
        source = Path(env.get("CHECK_CHANGES_DIR", ""))
        if source.is_dir():
            paths = [line for line in env.get("CHECK_PATHS", "").splitlines() if line]
            for refusal in lay_changes(source, paths, Path.cwd()):
                say(f"::warning::{env.get('CHECK_ID', 'check')}: not importing {refusal}")
        return 0
    try:
        return run_decision(argv[0], env)
    except EnvError as error:
        say(f"::error::the declared environment: {error}")
        return 1


def run_decision(command: str, env: Mapping[str, str]) -> int:
    """Run `prepare` or `key`: the two subcommands whose commands read the declared variables."""
    if command == "key":
        write_outputs(env, record_key(env))
        return 0
    decided = prepare(env)
    write_outputs(
        env,
        {
            "scope": decided.scope,
            "run": str(decided.run).lower(),
            "skip": str(decided.skip).lower(),
            "skip-reason": decided.skip_reason,
            "unavailable": decided.unavailable,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
