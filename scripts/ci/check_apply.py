#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Apply one check's mode to what its command did: report, block, commit, or propose a PR.

Run by `_check.yml` after the command, as `uv run --script` from a copy under
$RUNNER_TEMP (the `pr` mode switches branches, which would rewrite this file under the
interpreter reading it). Everything arrives through the environment; a variable this
script does not know is ignored, since `_check.yml@main` may run a consumer's older or
newer copy.

  CHECK_ID       the check id                                   (required)
  CHECK_MODE     its mode on this event: ignore|block|commit|pr (required)
  CHECK_EXIT     the command's exit status; blank = it never finished = a failure
  CHECK_LOG      the command's log file
  CHECK_UNAVAILABLE   a reason when the check could not be verified at all (a workflow that
                 had no secrets, a judge that never ran); empty = it could
  CHECK_PATHS    newline-separated paths the command may change; empty = none
  CHECK_TITLE    title of the PR the `pr` mode opens
  CHECK_NOTE     appended to that PR's body
  APP_TOKEN      the App token; empty = `commit`/`pr` behave as `block`
  APP_SLUG       the App's slug, for the bot identity
  GITHUB_EVENT_NAME, GITHUB_REPOSITORY, GITHUB_OUTPUT   as on a runner
  PR_NUMBER, PR_HEAD_REF, PR_HEAD_REPO                   the pull_request, when there is one
  MERGE_GROUP_HEAD_REF   the merge_group's queue ref, whose `pr-<n>-<sha>` names the PR at its tip
  BASE_BRANCH    the default branch (default: main)
  RUN_URL        link to this run, quoted in bodies
  CHECK_REMOTE   where to push (default: the repo on github.com, authenticated by APP_TOKEN)

Writes `result` (success|failure) and `blocking` (true|false) to $GITHUB_OUTPUT when it
is set, and exits 1 exactly when `blocking` is true. A git or gh call that fails
unexpectedly ends the run with that command's exit status and no outputs.

On a merge queue candidate `pr` proposes the changes to the PR the queue ref names, exactly
as on a pull_request: a side PR onto that PR's branch (the branch itself is locked while
queued) and a changes-requested review, then a failed run so the PR leaves the queue. Only
the check's own paths travel, laid over the PR's own tip, so content of the other PRs in the
group never reaches it.

A check that could not be verified is never a pass: it blocks wherever the mode blocks, with
the reason in the log, and is reported `skipped` (never red) only under `ignore`.

Three rules hold in every mode: a failed command never pushes content, nothing is staged
outside CHECK_PATHS, and the bot never pushes a file under `.github/workflows/` — a change
there is run locally by the developer, and none of the changes beside it are proposed.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple, NoReturn, Self

FAILED_LABEL = "check-failed"
# GitHub caps a body at 65536 characters; the tail of a log is where the failure is.
LOG_TAIL_BYTES = 60000
WORKFLOWS_PREFIX = ".github/workflows/"
WORKFLOW_ADVICE = "the bot never pushes .github/workflows/ files: run the check locally and commit the result"
CHANGES_REQUESTED = "CHANGES_REQUESTED"
# Files are read and written byte-exact: a log or a file name is not always valid UTF-8.
TEXT_ERRORS = "surrogateescape"
# `refs/heads/gh-readonly-queue/<base>/pr-<n>-<sha>`: the only place a merge_group event
# names a PR, and GitHub's shape rather than ours. The base may itself hold slashes.
QUEUE_REF = re.compile(r"(?:^|/)gh-readonly-queue/.+/pr-(\d+)-[0-9a-f]{40}$")


class Finish(Exception):  # noqa: N818 -- a verdict, not an error
    """The run's verdict; `main` turns it into outputs and an exit status."""

    def __init__(self, result: str, blocking: bool) -> None:
        """Carry the verdict."""
        super().__init__(result, blocking)
        self.result = result
        self.blocking = blocking


class MissingVariableError(Exception):
    """A required environment variable is unset or empty."""


class OpenPr(NamedTuple):
    """The open PR whose head is a given branch."""

    number: str
    # Kept whole: GitHub allows a comma inside a label name.
    labels: tuple[str, ...]


class Saved(NamedTuple):
    """The deletions to replay; the changed files travel in a tar beside them."""

    deleted: list[bytes]


class Config(NamedTuple):
    """The environment contract, defaults applied."""

    check_id: str
    mode: str
    exit_status: str
    log: str
    unavailable: str
    paths: tuple[str, ...]
    title: str
    note: str
    app_token: str
    app_slug: str
    event: str
    repository: str
    pr_number: str
    pr_head_ref: str
    pr_head_repo: str
    queue_ref: str
    base_branch: str
    run_url: str
    remote: str
    github_output: str

    @property
    def marker(self) -> str:
        """The hidden comment that ties a PR, review or comment to this check."""
        return f"<!-- dockyard-check:{self.check_id} -->"

    @property
    def trailer(self) -> str:
        """The commit trailer that marks this check's own commits."""
        return f"Dockyard-Check: {self.check_id}"

    @property
    def on_pr(self) -> bool:
        """Whether the run is a pull_request event."""
        return self.event == "pull_request"

    @property
    def on_queue(self) -> bool:
        """Whether the run is a merge_group event: a candidate, not a branch anyone can push to."""
        return self.event == "merge_group"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        """Read the contract, treating an empty variable as unset like `${VAR:-default}`."""

        def get(name: str, default: str = "") -> str:
            return env.get(name) or default

        for required in ("CHECK_ID", "CHECK_MODE"):
            if not get(required):
                raise MissingVariableError(f"{required}: parameter null or not set")
        token = get("APP_TOKEN")
        repository = get("GITHUB_REPOSITORY")
        return cls(
            check_id=get("CHECK_ID"),
            mode=get("CHECK_MODE"),
            exit_status=get("CHECK_EXIT"),
            log=get("CHECK_LOG", "/dev/null"),
            unavailable=get("CHECK_UNAVAILABLE"),
            paths=tuple(line for line in get("CHECK_PATHS").split("\n") if line),
            title=get("CHECK_TITLE"),
            note=get("CHECK_NOTE"),
            app_token=token,
            app_slug=get("APP_SLUG", "dockyard"),
            event=get("GITHUB_EVENT_NAME"),
            repository=repository,
            pr_number=get("PR_NUMBER"),
            pr_head_ref=get("PR_HEAD_REF"),
            pr_head_repo=get("PR_HEAD_REPO"),
            queue_ref=get("MERGE_GROUP_HEAD_REF"),
            base_branch=get("BASE_BRANCH", "main"),
            run_url=get("RUN_URL"),
            remote=get("CHECK_REMOTE", f"https://x-access-token:{token}@github.com/{repository}.git"),
            github_output=get("GITHUB_OUTPUT"),
        )


def say(message: str, *, err: bool = False) -> None:
    """Print a line, flushed so it precedes the output of the git/gh call after it."""
    print(message, file=sys.stderr if err else sys.stdout, flush=True)


class Shell:
    """Run git, gh and tar in the current directory, `gh` authenticated as the App.

    A call that fails without `check=False` ends the process with the command's own exit
    status, as `set -e` did; the command's stderr has already said why.
    """

    def __init__(self, environ: Mapping[str, str], app_token: str) -> None:
        """Fix the environment every subprocess runs in."""
        # `gh` authenticates as the App; the command's own GH_TOKEN, if any, is not this one.
        self.env = {**environ, "GH_TOKEN": app_token}

    def _run(
        self,
        argv: Sequence[str],
        *,
        capture: bool,
        check: bool,
        mute_stdout: bool = False,
        mute_stderr: bool = False,
    ) -> "subprocess.CompletedProcess[bytes]":
        sys.stdout.flush()
        sys.stderr.flush()
        stdout = subprocess.PIPE if capture else (subprocess.DEVNULL if mute_stdout else None)
        done = subprocess.run(  # noqa: S603 -- fixed argv, no shell
            list(argv),
            env=self.env,
            stdout=stdout,
            stderr=subprocess.DEVNULL if mute_stderr else None,
            check=False,
        )
        if check and done.returncode != 0:
            raise SystemExit(done.returncode)
        return done

    def call(self, *argv: str, check: bool = True) -> int:
        """Run with output passed through; return the exit status."""
        return self._run(argv, capture=False, check=check).returncode

    def call_muted(self, *argv: str, stderr: bool) -> int:
        """Run with stdout (and stderr, if asked) discarded; return the exit status."""
        return self._run(argv, capture=False, check=False, mute_stdout=True, mute_stderr=stderr).returncode

    def read(self, *argv: str, check: bool = True) -> str:
        """Run and return stdout as text (stderr passes through)."""
        return self._run(argv, capture=True, check=check).stdout.decode(errors=TEXT_ERRORS)

    def read_bytes(self, *argv: str) -> bytes:
        """Run and return stdout unchanged."""
        return self._run(argv, capture=True, check=True).stdout


def chomp(text: str) -> str:
    """Drop trailing newlines, as a shell command substitution does."""
    return text.rstrip("\n")


def workflow_files_in(name_only_z: bytes) -> list[str]:
    """Return the paths of a `git diff --name-only -z` listing that sit under `.github/workflows/`.

    NUL-separated, never line-separated: a plain listing quotes a non-ASCII path and
    octal-escapes its bytes, so it no longer starts with the prefix, and that workflow file
    would be pushed.
    """
    names = [raw.decode(errors=TEXT_ERRORS) for raw in name_only_z.split(b"\0") if raw]
    return [name for name in names if name.startswith(WORKFLOWS_PREFIX)]


def log_excerpt(path: str) -> str:
    """Return the tail of the log in a Markdown fence; an unreadable log is an empty fence."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        data = b""
    tail = data[-LOG_TAIL_BYTES:].decode(errors=TEXT_ERRORS).replace("\0", "")
    return f"```\n{chomp(tail)}\n```\n"


def queued_pr_number(queue_ref: str) -> str:
    """Return the number of the PR a merge queue ref names, or '' when it names none."""
    found = QUEUE_REF.search(queue_ref)
    return found.group(1) if found else ""


def parse_open_pr(listing: str) -> OpenPr | None:
    """Return the first PR of a `gh pr list --json number,isDraft,labels` answer, if any."""
    if not listing.strip():
        return None
    prs = json.loads(listing)
    if not prs:
        return None
    first = prs[0]
    return OpenPr(str(first["number"]), tuple(str(label["name"]) for label in first["labels"]))


def _json_documents(text: str) -> list[object]:
    """Every JSON document in `text`; `gh api --paginate` prints one array per page."""
    decoder = json.JSONDecoder()
    documents: list[object] = []
    position = 0
    while True:
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            return documents
        document, position = decoder.raw_decode(text, position)
        documents.append(document)


def find_active_review(reviews: str, marker: str) -> str:
    """Return the id of the first review still requesting changes that carries `marker`, or ''."""
    for page in _json_documents(reviews):
        if not isinstance(page, list):
            continue
        for review in page:
            if not isinstance(review, dict) or review.get("state") != CHANGES_REQUESTED:
                continue
            body = review.get("body")
            if isinstance(body, str) and marker in body:
                return str(review["id"])
    return ""


def split_name_status(raw: bytes) -> tuple[list[bytes], list[bytes]]:
    """Split `--name-status -z` output into (kept files, deleted files)."""
    tokens = raw.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    kept: list[bytes] = []
    deleted: list[bytes] = []
    for status, name in zip(tokens[0::2], tokens[1::2], strict=False):
        (deleted if status == b"D" else kept).append(name)
    return kept, deleted


class Applier:
    """One check's mode applied to the working tree its command left behind."""

    def __init__(self, cfg: Config, shell: Shell) -> None:
        """Start with nothing staged; `collect_changes` fills the rest in."""
        self.cfg = cfg
        self.shell = shell
        self.failed = cfg.exit_status != "0"
        self.staged: list[str] = []
        self.changes = ""
        self.workflow_files: list[str] = []

    # -------------------------------------------------------------------- observation

    def present_paths(self) -> list[str]:
        """Return the paths git can stage: present on disk, or tracked (a deletion).

        A path that is neither is simply no change — `git add` would otherwise die on the
        unmatched pathspec. A glob is asked of git, tracked or not, so a first file under it
        counts.
        """
        return [
            path
            for path in self.cfg.paths
            if Path(path).exists()
            or chomp(
                self.shell.read(
                    "git", "ls-files", "--cached", "--others", "--exclude-standard", "--", path, check=False
                )
            )
        ]

    def stage(self) -> None:
        """Stage the check's paths — so a new file counts — and nothing outside them."""
        self.staged = self.present_paths()
        if self.staged:
            self.shell.call("git", "add", "-A", "--", *self.staged)

    def collect_changes(self) -> None:
        """Stage, report what changed, and note any changed workflow file."""
        if self.cfg.paths:
            self.stage()
            if self.staged:
                status = self.shell.read(
                    "git", "diff", "--cached", "--no-renames", "--name-status", "--", *self.staged
                )
                self.changes = chomp(status)
        if not self.changes:
            return
        say("Changes over the check's paths:")
        say(self.changes)
        self.shell.call("git", "--no-pager", "diff", "--cached", "--no-renames", "--stat", "--", *self.staged)
        # A token able to write under `.github/workflows/` can grant itself any secret, so
        # no check asks for that permission and none of these files is pushed.
        names = self.shell.read_bytes(
            "git", "diff", "--cached", "--no-renames", "--name-only", "-z", "--", *self.staged
        )
        self.workflow_files = workflow_files_in(names)

    # ------------------------------------------------------------------------ bodies

    def title(self) -> str:
        """Return the PR and commit title."""
        return chomp(self.cfg.title or f"chore: apply the {self.cfg.check_id} check")

    def run_link(self) -> str:
        """` — [run](url)` when the run's URL is known."""
        return f" — [run]({self.cfg.run_url})" if self.cfg.run_url else ""

    def failure_body(self) -> str:
        """Return the body of a PR that tracks a failed (or workflow-touching) check."""
        cfg = self.cfg
        verb = "changes workflow files" if self.workflow_files else "failed"
        if self.cfg.unavailable:
            verb = f"could not be verified ({self.cfg.unavailable})"
        parts = [f"{cfg.marker}\nThe check `{cfg.check_id}` {verb}{self.run_link()}.\n\n"]
        if self.workflow_files:
            parts.append(f"Nothing was proposed: {WORKFLOW_ADVICE}.\n\n")
            parts.extend(f"- `{name}`\n" for name in self.workflow_files)
            parts.append("\n")
        parts.append(log_excerpt(cfg.log))
        return chomp("".join(parts))

    def pr_body(self) -> str:
        """Return the body of the PR that proposes the check's changes."""
        cfg = self.cfg
        note = f"\n{cfg.note}\n" if cfg.note else ""
        return chomp(f"{cfg.marker}\nProposed by the check `{cfg.check_id}`{self.run_link()}.\n{note}\n")

    # ---------------------------------------------------------------------- verdicts

    def block(self, notice: str = "") -> NoReturn:
        """Fail on a failed command or on changes; otherwise pass. Always ends the run."""
        check_id = self.cfg.check_id
        if notice:
            say(f"::notice::{notice}")
        if self.failed:
            say(f"::error::check {check_id} failed")
            raise Finish("failure", True)
        if self.changes:
            say(f"::error::check {check_id} changed files it owns — run it locally and commit the result")
            raise Finish("failure", True)
        raise Finish("success", False)

    def bot_identity(self) -> None:
        """Commit as the App's bot."""
        slug = self.cfg.app_slug
        self.shell.call("git", "config", "user.name", f"{slug}[bot]")
        self.shell.call("git", "config", "user.email", f"{slug}[bot]@users.noreply.github.com")

    def remote_sha(self, branch: str) -> str:
        """Return the sha a remote branch points at, or '' when it does not exist.

        It is the lease a force-push is conditioned on, so a push that raced another run
        fails instead of winning.
        """
        listing = self.shell.read("git", "ls-remote", self.cfg.remote, f"refs/heads/{branch}", check=False)
        return "\n".join(line.split("\t")[0] for line in listing.splitlines())

    def push_or_fail(self, *args: str) -> None:
        """Push, turning a refusal into a blocking verdict.

        Without one the job ends with no outputs and the gate reads a blank. git's own
        message above says why (a protected branch, a lease another run won).
        """
        if self.shell.call("git", "push", *args, check=False) == 0:
            return
        say(f"::error::check {self.cfg.check_id}: the push was refused — see git's message above.", err=True)
        raise Finish("failure", True)

    def push_branch(self, branch: str) -> None:
        """Force-push HEAD to `branch`, leased on what the remote held a moment ago."""
        lease = f"--force-with-lease=refs/heads/{branch}:{self.remote_sha(branch)}"
        self.push_or_fail(lease, self.cfg.remote, f"HEAD:refs/heads/{branch}")

    def open_pr(self, branch: str) -> OpenPr | None:
        """Return the open PR whose head is `branch`."""
        listing = self.shell.read(
            "gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number,isDraft,labels"
        )
        return parse_open_pr(listing)

    def active_review(self) -> str:
        """Return the id of this check's standing changes-requested review on the PR, or ''."""
        cfg = self.cfg
        reviews = self.shell.read("gh", "api", f"repos/{cfg.repository}/pulls/{cfg.pr_number}/reviews", "--paginate")
        return find_active_review(reviews, cfg.marker)

    # ------------------------------------------------------------------------- flow

    def run(self) -> NoReturn:
        """Apply the mode. Every path ends in a `Finish`."""
        cfg = self.cfg
        if cfg.unavailable:
            self.report_unavailable()
        self.collect_changes()
        if cfg.mode == "ignore":
            raise Finish("failure" if self.failed or self.changes else "success", False)
        if cfg.mode == "block":
            self.block()
        if cfg.mode not in ("commit", "pr"):
            say(f"::error::check_apply.py: unknown mode '{cfg.mode}'", err=True)
            raise Finish("failure", True)
        if not cfg.app_token:
            self.block(
                f"check {cfg.check_id} runs as block: `{cfg.mode}` needs the GH_APP_PRIVATE_KEY secret, "
                "and this run has no App token"
            )
        if cfg.on_pr and cfg.pr_head_repo and cfg.pr_head_repo != cfg.repository:
            self.block(f"check {cfg.check_id} runs as block: the PR comes from a fork, which the App cannot push to")
        self.refuse_workflow_files()
        if cfg.mode == "commit":
            self.apply_commit()
        if cfg.on_queue:
            self.adopt_queued_pr()
        if cfg.on_pr or cfg.on_queue:
            self.apply_pr_on_pull_request()
        self.apply_pr_on_push()

    def report_unavailable(self) -> NoReturn:
        """End a run whose check could not be verified: red wherever the mode blocks, never green."""
        cfg = self.cfg
        say(f"::warning::check {cfg.check_id} could not be verified: {cfg.unavailable}")
        if cfg.mode == "ignore":
            raise Finish("skipped", False)
        say(f"::error::check {cfg.check_id} could not be verified, which blocks: {cfg.unavailable}")
        if cfg.mode == "pr" and cfg.app_token and not (cfg.on_pr or cfg.on_queue):
            # Nobody reads a red cron run: track it as a draft PR, as a failed command is.
            branch = f"check/{cfg.check_id}"
            self.track_failure(branch, self.open_pr(branch))
        raise Finish("failure", True)

    def adopt_queued_pr(self) -> None:
        """Make the PR the queue ref names this run's PR, or block when it cannot be proposed to.

        The candidate is the base plus every PR ahead of this one, so the run has no PR of its
        own: the ref's `pr-<n>` is the only thing that says which one the queue is checking.

        With nothing to propose there is no PR to name: reading it (a `gh pr view`, a fork
        check) could only turn a clean pass red, so the run ends here, red only if the command was.
        """
        cfg = self.cfg
        if not self.changes:
            self.block()
        number = queued_pr_number(cfg.queue_ref)
        if not number:
            self.block(f"check {cfg.check_id} runs as block: the queue ref {cfg.queue_ref!r} names no pull request")
        view = self.shell.read("gh", "pr", "view", number, "--json", "headRefName,isCrossRepository", check=False)
        try:
            pr = json.loads(view)
            head_ref, cross_repository = str(pr["headRefName"]), bool(pr["isCrossRepository"])
        except (ValueError, KeyError, TypeError):
            self.block(f"check {cfg.check_id} runs as block: could not read PR #{number} from the queue ref")
        if cross_repository:
            self.block(
                f"check {cfg.check_id} runs as block: PR #{number} comes from a fork, which the App cannot push to"
            )
        self.cfg = cfg._replace(pr_number=number, pr_head_ref=head_ref)

    def refuse_workflow_files(self) -> None:
        """Push nothing when a workflow file is among the changes.

        On a PR that is a plain block; from push, cron or dispatch it is tracked like a
        failure, since nobody reads a red cron run.
        """
        if not self.workflow_files:
            return
        say(f"::error::check {self.cfg.check_id}: {WORKFLOW_ADVICE}")
        say("\n".join(self.workflow_files))
        if self.cfg.on_pr or self.cfg.on_queue:
            raise Finish("failure", True)
        self.failed = True

    def apply_commit(self) -> NoReturn:
        """Commit the changes onto the PR's own branch, then fail so the new commit re-runs."""
        cfg = self.cfg
        if not cfg.on_pr or not cfg.pr_head_ref:
            self.block(f"check {cfg.check_id} runs as block: `commit` only means something on a pull request")
        if self.failed or not self.changes:
            self.block()
        # The loop breaker: this check's own commit is already the tip and still leaves
        # changes, so the command is not converging — another commit would only trigger
        # another run.
        tip = self.shell.read("git", "log", "-1", "--format=%B", check=False)
        if cfg.trailer in tip.splitlines():
            self.block(f"check {cfg.check_id} still changes files right after its own commit — not pushing again")
        self.bot_identity()
        self.shell.call("git", "commit", "-q", "-m", f"chore: apply the {cfg.check_id} check", "-m", cfg.trailer)
        self.push_or_fail(cfg.remote, f"HEAD:refs/heads/{cfg.pr_head_ref}")
        say(f"::error::check {cfg.check_id} committed its changes to {cfg.pr_head_ref}; the new commit re-runs it")
        raise Finish("failure", True)

    def dismiss_review(self, review: str) -> None:
        """Dismiss the standing review, or say in a comment that it could not be."""
        cfg = self.cfg
        dismissed = self.shell.call_muted(
            "gh",
            "api",
            "-X",
            "PUT",
            f"repos/{cfg.repository}/pulls/{cfg.pr_number}/reviews/{review}/dismissals",
            "-f",
            f"message=The check `{cfg.check_id}` passes now.",
            "-f",
            "event=DISMISS",
            stderr=False,
        )
        if dismissed != 0:
            self.shell.call(
                "gh",
                "pr",
                "comment",
                cfg.pr_number,
                "--body",
                f"{cfg.marker} The check `{cfg.check_id}` passes now; its review could not be dismissed.",
            )

    def close_pr(self, pr: OpenPr, comment: str) -> None:
        """Close the PR and delete its branch, saying why."""
        self.shell.call("gh", "pr", "close", pr.number, "--delete-branch", "--comment", comment)

    def create_pr(self, *, base: str, head: str, body: str, draft: bool = False, label: str = "") -> None:
        """Open a PR from `head` onto `base`, titled like the commits."""
        argv = ["gh", "pr", "create"]
        argv += ["--draft"] if draft else []
        argv += ["--base", base, "--head", head, "--title", self.title()]
        argv += ["--label", label] if label else []
        self.shell.call(*argv, "--body", body)

    def apply_pr_on_pull_request(self) -> NoReturn:
        """Propose the changes as a side PR onto the PR's branch and request changes.

        The PR is the pull request itself, or on the merge queue the one the queue ref names.
        There the branch is locked while queued, which is why the proposal is a side PR and
        not a push; the failed run is what takes the PR out of the queue.
        """
        cfg = self.cfg
        # A check's own PR — the cron one or a side PR — is never answered with another side PR.
        if cfg.pr_head_ref.startswith(("check/", "check-pr/")):
            self.block(f"check {cfg.check_id} runs as block on its own PR")
        if self.failed:
            self.block()
        # Not `check/<id>/pr-<N>`: git cannot hold that ref beside `check/<id>`, the cron's own.
        branch = f"check-pr/{cfg.check_id}/{cfg.pr_number}"
        existing = self.open_pr(branch)
        review = self.active_review()

        if not self.changes:
            if review:
                self.dismiss_review(review)
            if existing:
                self.close_pr(existing, f"The check `{cfg.check_id}` passes on #{cfg.pr_number} now.")
            raise Finish("success", False)

        self.bot_identity()
        if cfg.on_queue:
            self.lay_changes_onto_queued_pr(branch)
        else:
            self.shell.call("git", "switch", "-q", "-C", branch)
        self.shell.call("git", "commit", "-q", "-m", self.title(), "-m", cfg.trailer)
        self.push_branch(branch)
        if not existing:
            self.create_pr(base=cfg.pr_head_ref, head=branch, body=self.pr_body())
        if not review:
            self.shell.call(
                "gh",
                "pr",
                "review",
                cfg.pr_number,
                "--request-changes",
                "--body",
                self.review_body(branch),
            )
        say(f"::error::check {cfg.check_id} proposed its changes on {branch}")
        raise Finish("failure", True)

    def review_body(self, branch: str) -> str:
        """Return the changes-requested review that points at the side PR."""
        cfg = self.cfg
        text = (
            f"{cfg.marker} The check `{cfg.check_id}` changed files; its fix is proposed on `{branch}`. "
            "Merge that PR into this branch."
        )
        if cfg.on_queue:
            text += (
                f" It ran on the merge queue's candidate, where `{cfg.pr_head_ref}` is locked, hence the side "
                "branch. If the group held several pull requests the change may come from a sibling rather "
                "than this one: the diff says which."
            )
        return text

    def ensure_failed_label(self) -> None:
        """Create the label failure PRs carry; an existing one is fine, any failure is not fatal."""
        description = "A dockyard check failed"
        argv = ("gh", "label", "create", FAILED_LABEL, "--color", "B60205", "--description", description, "--force")
        self.shell.call_muted(*argv, stderr=True)

    def track_failure(self, branch: str, existing: OpenPr | None) -> NoReturn:
        """Track a failed check as a PR, and end the run red.

        Tracked AND red: a green run beside a draft PR is a failure nobody is told about.
        A PR carrying real changes is not force-pushed over: it goes back to draft, and the
        failure is appended where a reviewer will see it. With no PR, the failure is a draft
        PR whose only commit is empty (no issue outcome).
        """
        cfg = self.cfg
        base = cfg.base_branch
        self.ensure_failed_label()
        if existing and FAILED_LABEL not in existing.labels:
            self.shell.call("gh", "pr", "ready", existing.number, "--undo", check=False)
            self.shell.call("gh", "pr", "edit", existing.number, "--add-label", FAILED_LABEL)
            self.shell.call("gh", "pr", "comment", existing.number, "--body", self.failure_body())
        elif existing:
            self.shell.call("gh", "pr", "edit", existing.number, "--body", self.failure_body())
        else:
            self.shell.call("git", "reset", "-q", "--hard")
            self.bot_identity()
            self.shell.call("git", "switch", "-q", "-C", branch, f"origin/{base}")
            self.shell.call(
                "git", "commit", "-q", "--allow-empty", "-m", f"{self.title()} — failing", "-m", cfg.trailer
            )
            self.push_branch(branch)
            self.create_pr(base=base, head=branch, body=self.failure_body(), draft=True, label=FAILED_LABEL)
        raise Finish("failure", True)

    def save_changes(self, work: Path) -> Saved:
        """Save the changed files (in a tar) and the deletions, to lay onto another base.

        NUL-delimited end to end: `--name-status` without `-z` quotes a non-ASCII or
        unusual name, which `tar` would then look for literally.
        """
        raw = self.shell.read_bytes(
            "git", "diff", "--cached", "--no-renames", "--name-status", "-z", "--", *self.staged
        )
        kept, deleted = split_name_status(raw)
        if kept:
            listing = work / "kept"
            listing.write_bytes(b"".join(name + b"\0" for name in kept))
            self.shell.call("tar", "--null", "-cf", str(work / "files.tar"), "-T", str(listing))
        return Saved(deleted)

    def restore_changes(self, work: Path, saved: Saved) -> None:
        """Lay the saved changes onto the current tree and stage them."""
        archive = work / "files.tar"
        if archive.is_file():
            self.shell.call("tar", "-xf", str(archive))
        for name in saved.deleted:
            Path(os.fsdecode(name)).unlink(missing_ok=True)
        self.stage()

    def rebase_changes_onto(self, ref: str, branch: str) -> None:
        """Re-apply the changes on `ref`'s tip as `branch`, clearing them if none remain.

        Changes relative to where the command ran can vanish on that tip; then there is
        nothing to propose.
        """
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            saved = self.save_changes(work)
            self.shell.call("git", "reset", "-q", "--hard")
            self.shell.call("git", "switch", "-q", "-C", branch, ref)
            self.restore_changes(work, saved)
        if (
            not self.staged
            or self.shell.call("git", "diff", "--cached", "--quiet", "--", *self.staged, check=False) == 0
        ):
            self.changes = ""

    def lay_changes_onto_queued_pr(self, branch: str) -> None:
        """Move the changes from the queue candidate onto the PR's own tip, as `branch`.

        The candidate holds every PR ahead of this one; only the check's own paths are carried,
        and they are laid over the PR's tip, so nothing of a sibling PR travels with them.
        """
        cfg = self.cfg
        head = cfg.pr_head_ref
        self.shell.call("git", "fetch", "-q", cfg.remote, f"+refs/heads/{head}:refs/remotes/origin/{head}")
        self.rebase_changes_onto(f"origin/{head}", branch)
        if not self.changes:
            say(
                f"::error::check {cfg.check_id}: the queue candidate differs from the checked-out result, but PR "
                f"#{cfg.pr_number}'s branch already holds it — the change comes from a sibling PR in the "
                "merge group; run the check locally"
            )
            raise Finish("failure", True)

    def apply_pr_on_push(self) -> NoReturn:
        """From push, cron or dispatch: keep one PR from `check/<id>` onto the base branch."""
        cfg = self.cfg
        branch = f"check/{cfg.check_id}"
        existing = self.open_pr(branch)
        if self.failed:
            self.track_failure(branch, existing)
        if self.changes:
            self.rebase_changes_onto(f"origin/{cfg.base_branch}", branch)
        if not self.changes:
            if existing:
                self.close_pr(existing, f"The check `{cfg.check_id}` passes on `{cfg.base_branch}` now.")
            raise Finish("success", False)
        self.bot_identity()
        self.shell.call("git", "commit", "-q", "-m", self.title(), "-m", cfg.trailer)
        self.push_branch(branch)
        if existing:
            self.shell.call(
                "gh",
                "pr",
                "edit",
                existing.number,
                "--title",
                self.title(),
                "--body",
                self.pr_body(),
                "--remove-label",
                FAILED_LABEL,
            )
            self.shell.call("gh", "pr", "ready", existing.number, check=False)
        else:
            self.create_pr(base=cfg.base_branch, head=branch, body=self.pr_body())
        raise Finish("success", False)


def report(cfg: Config, verdict: Finish) -> int:
    """Publish the verdict to $GITHUB_OUTPUT and stdout; return the exit status."""
    result = verdict.result
    blocking = "true" if verdict.blocking else "false"
    if cfg.github_output:
        with Path(cfg.github_output).open("a", encoding="utf-8") as out:
            out.write(f"result={result}\nblocking={blocking}\n")
    say(f"check {cfg.check_id}: {result} (blocking: {blocking})")
    return 1 if verdict.blocking else 0


def main(environ: Mapping[str, str] | None = None) -> int:
    """Apply the mode described by the environment; return the exit status."""
    env = os.environ if environ is None else environ
    try:
        cfg = Config.from_env(env)
    except MissingVariableError as exc:
        say(f"check_apply.py: {exc}", err=True)
        return 1
    try:
        Applier(cfg, Shell(env, cfg.app_token)).run()
    except Finish as verdict:
        return report(cfg, verdict)


if __name__ == "__main__":
    sys.exit(main())
