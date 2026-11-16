#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""The level-A check: what is not a file.

Branch protection, required checks and the merge queue are platform state. They appear
in no file diff, so `dockyard check` is blind to them by construction, and a required
check that is required nowhere looks exactly like one that is enforced everywhere. This
script closes that hole the same way dockyard closes every other one: one written
statement of intent, and something that fails when reality drifts from it.

READ-ONLY. It makes `gh api` GET calls and nothing else — it never writes platform
state. Applying state, if ever wanted, is Terraform's job, in tetrixx-terraform.

The standard is the estate's, written below, and every repo is held to it: no `[platform]`
table is needed to opt in. `[platform]` in this repo's own `dockyard.toml` (per-repo, never
published) carries only how the repo DIFFERS. A repo with no `dockyard.toml`, or none that
mentions the platform, is checked against the standard as it stands: leaving branch
protection unread is the failure this check exists to end, and a repo that was never asked
to declare anything is exactly the one nobody is reading.

## An unreadable axis is never a value

GitHub answers the branch-protection endpoint with 404 both when a branch has NO
protection and when the token cannot read it, and the same shape recurs on the
Dependabot endpoints and the merge-queue query. Conflating the two reports the wrong
estate — a repo everybody can push to looks identical to one this script simply cannot
see. Every axis therefore has three outcomes, not two, and the exit status says which:

  0  every declared property matches
  1  drift: a declared property does not match reality (UNREADABLE lines still printed)
  2  not checkable: nothing drifted, but at least one axis could not be read — the
     protection itself, or one `UNREADABLE:` line

Exit 2 is deliberately not success. A check that cannot run is not a check that passed,
and the scheduled caller tracks it exactly as it would drift — the missing permission IS
the finding.

GitHub Environments are compared too, for every environment the repo deploys to (each
`[[deploy.target]]` of its own `dockyard.toml`). An Environment can express reviewers, a
wait timer and a deployment branch policy, and nothing else: it cannot require a status
check, so what it is compared on is exactly that. A repo with no deploy target has none to
hold to a standard, and the environments call is not made.

Env: GH_TOKEN with `administration:read` and `actions:read` on the repo. The default GITHUB_TOKEN does NOT
carry it, which is the chicken-and-egg architecture.md §9 names: the App that makes
verifying the declaration possible is itself the declaration's first entry.

Usage: platform_check.py [repo_root]
"""

import io
import json
import os
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import NamedTuple, Self

DECL = "dockyard.toml"

# The estate's level-A standard, and the reason a repo's own `[platform]` table stays
# short: it declares only what DIFFERS from this, exactly as `dockyard.toml` already works
# for everything else. Restating a default in a repo is a second place to update when the
# default moves.
#
# The standard is the merge queue: it tests the merged result, so a branch need not be up
# to date to be queued (`strict-up-to-date` off), and nothing is exempt from review (no
# bypass users, teams or apps). Every PR needs a code owner's approval.
#
# `required-checks` defaults to the verdict job alone. It already ANDs every check the
# generated `ci.yml` runs, so requiring it requires them all and adding a check never
# means editing a branch-protection rule. A repo with a gate of its own (an eval gate
# outside `ci.yml`) declares the whole list, as a list replaces rather than extends.
_DEFAULTS: dict[str, object] = {
    "branch": "main",
    "enforce-admins": True,
    "required-reviews": 1,
    "required-conversation-resolution": True,
    "required-linear-history": True,
    "last-push-approval": True,
    "required-checks": ["CI Failure Report / CI Gate"],
    "strict-up-to-date": False,
    "code-owner-reviews": True,
    "dismiss-stale-reviews": False,
    "required-signatures": False,
    "allow-force-pushes": False,
    "allow-deletions": False,
    "block-creations": False,
    "lock-branch": False,
    "merge-queue": True,
    "merge-queue-method": "REBASE",
    "merge-queue-strategy": "ALLGREEN",
    "merge-queue-min-entries": 1,
    "merge-queue-max-entries": 5,
    "merge-queue-max-build": 1,
    "merge-queue-min-wait-seconds": 300,
    "merge-queue-check-timeout-seconds": 3600,
    "allow-merge-commit": False,
    "vulnerability-alerts": True,
    "security-updates-paused": False,
    "allowed-bypass-users": [],
    "allowed-bypass-teams": [],
    "allowed-bypass-apps": [],
    "allowed-dismissal-users": [],
    "allowed-push-users": [],
    "allowed-push-teams": [],
    "allowed-push-apps": [],
}


# The estate's standard for a GitHub Environment, by class, read back from `GET
# /repos/{repo}/environments`. Measured 2026-10-28 on the repos that deploy through dockyard
# targets, doc-station and agent-forge: their 10 environments carry no protection rule at all
# (no reviewer, no wait timer) and no deployment branch policy, so any branch's workflow run
# can use an environment's secrets. Other repos were not the measure, and one outside
# dockyard does protect an environment. What the standard asks for beyond that is one thing, for the environments that
# are a client's own (`<client>-<stage>`): a deployment branch policy of "protected", so a
# feature branch cannot deploy to a client. The shared `dev` and `demo` stay open to any
# branch, which is how they are used. Required reviewers and a wait timer default to none
# everywhere: a human approval on top of a manual dispatch is a decision a repo makes, by
# declaring it, rather than one the estate imposes.
#
# A repo's `[platform.environments.<id>]` overrides one key of one environment.
_SHARED_ENVIRONMENT: dict[str, object] = {
    "required-reviewers": 0,
    "prevent-self-review": False,
    "wait-timer": 0,
    "deployment-branch-policy": "any",
}
_CLIENT_ENVIRONMENT: dict[str, object] = _SHARED_ENVIRONMENT | {"deployment-branch-policy": "protected"}
_SHARED_ENVIRONMENT_IDS = frozenset({"dev", "demo"})


class Finish(Exception):  # noqa: N818 -- control flow carrying an exit status, not an error
    """Stop the run with this exit status."""

    def __init__(self, code: int) -> None:
        """Carry the exit status."""
        super().__init__(code)
        self.code = code


class GhResult(NamedTuple):
    """One `gh` call: exit status and both streams, trailing newlines stripped."""

    returncode: int
    stdout: str
    stderr: str


class Axis(NamedTuple):
    """A declaration key compared with one field of the protection payload."""

    key: str
    path: tuple[str, ...]


class Exemption(NamedTuple):
    """A list of principals the protection payload may carry, each needing a declaration."""

    key: str
    path: tuple[str, ...]
    leaf: str
    label: str


def jq_text(value: object) -> str:
    """Render a JSON value the way `jq -r` prints it."""
    match value:
        case None:
            return "null"
        case bool():
            return "true" if value else "false"
        case str():
            return value
        case list() | dict():
            return json.dumps(value, indent=2)
        case _:
            return str(value)


class Json:
    """A JSON value navigated the forgiving way jq does: a wrong step yields null."""

    def __init__(self, value: object) -> None:
        """Wrap an already-parsed JSON value."""
        self.value = value

    @classmethod
    def parse(cls, text: str) -> Self | None:
        """Parse JSON text, or return None when it is not JSON."""
        try:
            return cls(json.loads(text))
        except ValueError:
            return None

    def has(self, key: str) -> bool:
        """Say whether this is an object carrying the key, whatever its value."""
        return isinstance(self.value, dict) and key in self.value

    def at(self, *path: str) -> Self:
        """Follow object keys; any wrong step yields null."""
        node = self.value
        for step in path:
            node = node.get(step) if isinstance(node, dict) else None
        return type(self)(node)

    def items(self) -> list[Self]:
        """Return the elements of an array, and nothing for any other value."""
        return [type(self)(item) for item in self.value] if isinstance(self.value, list) else []

    def text(self) -> str:
        """Return the value as `jq -r` prints it."""
        return jq_text(self.value)

    def alt(self, fallback: str) -> str:
        """Return the text, or the fallback when null or false — jq's `//`."""
        return fallback if self.value is None or self.value is False else self.text()

    def declared(self, key: str) -> str | None:
        """Return one key as text, or None when absent or blank.

        Presence is `has`, never truthiness: a declared `false` is a statement, and
        reading it as "not declared" skipped the very line whose value was written down.
        A declaration that is silently not checked is worse than none: the first is
        believed.
        """
        if not self.has(key):
            return None
        return self.at(key).text() or None

    def merged(self, other: Self) -> Self:
        """Return this document overlaid by another, objects recursively — jq's `*`."""
        return type(self)(_merge(self.value, other.value))


def _merge(base: object, over: object) -> object:
    if isinstance(base, dict) and isinstance(over, dict):
        return base | {key: _merge(base[key], value) if key in base else value for key, value in over.items()}
    return over


class Report:
    """Findings so far; each is printed as it is found."""

    def __init__(self) -> None:
        """Start with no findings."""
        self.drifted = False
        self.unreadable = False

    def drift(self, message: str) -> None:
        """Report a declared property that does not match reality."""
        print(f"DRIFT: {message}", file=sys.stderr)
        self.drifted = True

    def cannot_read(self, message: str) -> None:
        """Report an axis the token could not read: never compared.

        Reading a failed call as "false" or "absent" is the one mistake this script
        exists not to make.
        """
        print(f"UNREADABLE: {message}", file=sys.stderr)
        self.unreadable = True


def gh(root: Path, *args: str) -> GhResult:
    """Run the `gh` CLI in the repo; a missing binary is a failed call, like a shell's 127."""
    command = ["gh", *args]  # noqa: S607 -- gh is resolved from PATH on purpose: tests stand one in
    try:
        done = subprocess.run(  # noqa: S603 -- fixed argv, no shell
            command, cwd=root, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL
        )
    except OSError as exc:
        return GhResult(127, "", str(exc))
    return GhResult(done.returncode, done.stdout.rstrip("\n"), done.stderr.rstrip("\n"))


def read_platform(decl: Path) -> Json:
    """Return the repo's `[platform]` table, empty when it declares none, or stop with 2 when unreadable.

    No file and no table are the same answer: nothing differs from the standard. The failure
    to READ is kept apart from that, and that is load-bearing: a declaration that cannot be
    read is exactly as unchecked as a platform that cannot be reached, so it exits 2 rather
    than reporting a clean tree.
    """
    if not decl.is_file():
        return Json({})
    try:
        with decl.open("rb") as fh:
            platform = tomllib.load(fh).get("platform")
        json.dumps(platform)
    except (OSError, ValueError, TypeError):
        print(f"platform-check: cannot read {DECL} — the file is not valid TOML.", file=sys.stderr)
        raise Finish(2) from None
    return Json({} if platform is None else platform)


def effective_declaration(platform: Json) -> Json:
    """Overlay the repo's declaration on the estate standard, key by key.

    A repo that declares nothing beyond its own required checks is held to the full
    standard, and one that needs to differ says so in one line, where a reviewer can see
    the exception rather than diffing twenty values to find it.

    Guard, not ceremony: this script has more than once found a way to report "every
    declared property matches" while doing no comparison at all. With nothing to compare
    against, the only honest answer is 2.
    """
    effective = Json(_DEFAULTS).merged(platform)
    if not isinstance(effective.value, dict):
        print(
            f"platform-check: could not build the effective declaration from the defaults and {DECL}.", file=sys.stderr
        )
        raise Finish(2)
    return effective


def repository(root: Path) -> str:
    """Return owner/name from GITHUB_REPOSITORY, else from `gh`, else stop with 2."""
    repo = (
        os.environ.get("GITHUB_REPOSITORY")
        or gh(root, "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").stdout
    )
    if not repo:
        print("platform-check: cannot determine the repository (set GITHUB_REPOSITORY).", file=sys.stderr)
        raise Finish(2)
    return repo


def read_protection(root: Path, repo: str, branch: str) -> Json:
    """Return the branch-protection payload, or stop: 1 if unprotected, 2 if unreadable.

    The two 404s tell themselves apart by their message, not by a separate probe: an
    unprotected branch answers "Branch not protected", a token that cannot read answers
    "Not Found" (or 403). Probing `.permissions.admin` first was wrong: it is the admin
    ROLE, which an App never holds, while reading protection needs only
    administration:read. `gh api` prints the response body to stdout on an error too,
    which is what is matched.
    """
    result = gh(root, "api", f"repos/{repo}/branches/{branch}/protection")
    if result.returncode != 0:
        if '"Branch not protected"' in result.stdout:
            print(f"DRIFT: branch {branch} has no protection at all, but [platform] declares some.", file=sys.stderr)
            raise Finish(1)
        print(f"platform-check: the token cannot read {repo}'s protection.", file=sys.stderr)
        print("  This is NOT evidence of an unprotected branch — it is the other 404. Grant the", file=sys.stderr)
        print("  App `administration:read` on this repo, or the check can never run here.", file=sys.stderr)
        raise Finish(2)
    protection = Json.parse(result.stdout)
    if protection is None:
        # A successful call with a body that is not JSON has read nothing: comparing it
        # would report every axis as false.
        print(f"platform-check: {repo}'s protection answered with a body that is not JSON.", file=sys.stderr)
        raise Finish(2)
    return protection


def check_required_checks(decl: Json, protection: Json, report: Report) -> None:
    """Compare required checks as a multiset, both ways round.

    An UNEXPECTED required check matters as much as a missing one: a required check
    nothing reports any more blocks every merge forever rather than failing them.

    Gated on the key being DECLARED, not on the list being non-empty: an empty list is a
    statement — "this branch should require nothing" — and every check present is then an
    extra to report.
    """
    if not decl.has("required-checks"):
        return
    want = Counter(item.text() for item in decl.at("required-checks").items())
    have = Counter(c.at("context").text() for c in protection.at("required_status_checks", "checks").items())
    missing = sorted((want - have).elements())
    extra = sorted((have - want).elements())
    if missing:
        report.drift(f"declared required checks that are NOT required: {','.join(missing)}")
    if extra:
        report.drift(f"required checks nothing declares — stale ones block merges forever: {','.join(extra)}")


# Every branch-protection switch worth declaring, as a table rather than one hand-written
# comparison apiece: adding an axis is adding a line. The first version compared three of
# these and the estate census is what showed how little that covered — dockyard sat on
# `require_last_push_approval: false` and `required_linear_history: false` while BOTH other
# repos had them on, and no check could have said so, because level A only exists where
# something looks at it.
#
# The `allow_*` pair is declared to stay FALSE. They are the switches whose flip is
# invisible and expensive — force-push and branch deletion on the default branch — and the
# whole point of writing a disabled thing down is that nothing then re-enables it quietly.
_REVIEWS = "required_pull_request_reviews"
_AXES = (
    Axis("enforce-admins", ("enforce_admins", "enabled")),
    Axis("required-linear-history", ("required_linear_history", "enabled")),
    Axis("required-conversation-resolution", ("required_conversation_resolution", "enabled")),
    Axis("required-signatures", ("required_signatures", "enabled")),
    Axis("strict-up-to-date", ("required_status_checks", "strict")),
    Axis("dismiss-stale-reviews", (_REVIEWS, "dismiss_stale_reviews")),
    Axis("code-owner-reviews", (_REVIEWS, "require_code_owner_reviews")),
    Axis("last-push-approval", (_REVIEWS, "require_last_push_approval")),
    Axis("allow-force-pushes", ("allow_force_pushes", "enabled")),
    Axis("allow-deletions", ("allow_deletions", "enabled")),
    Axis("block-creations", ("block_creations", "enabled")),
    Axis("lock-branch", ("lock_branch", "enabled")),
)


def check_scalars(decl: Json, protection: Json, report: Report) -> None:
    """Compare every switch in the table, then the approving-review count."""
    for axis in _AXES:
        want = decl.declared(axis.key)
        if want is None:
            continue
        have = protection.at(*axis.path).alt("false")
        if want != have:
            report.drift(f"{axis.key}: declared {want}, actual {have}")
    want_reviews = decl.declared("required-reviews")
    if want_reviews is not None:
        have_reviews = protection.at(_REVIEWS, "required_approving_review_count").alt("0")
        if want_reviews != have_reviews:
            report.drift(f"required approving reviews: declared {want_reviews}, actual {have_reviews}")


def check_queue_presence(decl: Json, root: Path, repo: str, branch: str, report: Report) -> None:
    """Compare the merge queue's existence with the declaration.

    Not in the protection payload at all — it is a GraphQL-only property, and its absence
    there is why an estate can believe it has a queue it does not have.

    The raw payload is read, not a `--jq` projection: a failed query (a token the endpoint
    refuses, a GraphQL `errors` answer) has to be told apart from "no queue", and a
    projection flattens both to an empty string. A successful answer carries
    `"mergeQueue": null` for none; testing for a non-empty id rather than "not null" is
    what stops a blank line reading as a queue.
    """
    want = decl.declared("merge-queue")
    if want is None:
        return
    owner, name = repo.split("/", 1)[0], repo.rsplit("/", 1)[-1]
    query = f'{{ repository(owner:"{owner}",name:"{name}"){{ mergeQueue(branch:"{branch}"){{ id }} }} }}'
    result = gh(root, "api", "graphql", "-f", f"query={query}")
    payload = Json.parse(result.stdout) if result.returncode == 0 else None
    if payload is None or not payload.has("data") or payload.has("errors"):
        report.cannot_read(f"merge queue on {branch}: cannot read (the GraphQL query failed)")
        return
    have = "true" if payload.at("data", "repository", "mergeQueue", "id").alt("") else "false"
    if want != have:
        report.drift(f"merge queue on {branch}: declared {want}, actual {have}")


# The queue's settings are standardised rather than left to each repo because the three
# repos had already drifted apart while nobody watched: build concurrency was 5, 5 and 1,
# and one of those changed between two readings a day apart. The standard is agent-forge's,
# chosen deliberately: one entry building at a time means every pull request is tested
# alone on the real `main`. With larger groups, a single stale FILEMAP — which cannot
# self-heal inside a merge group, having no branch to push to — fails the whole group and
# rebuilds every entry in it.
_QUEUE_AXES = (
    Axis("merge-queue-method", ("mergeMethod",)),
    Axis("merge-queue-strategy", ("mergingStrategy",)),
    Axis("merge-queue-min-entries", ("minimumEntriesToMerge",)),
    Axis("merge-queue-max-entries", ("maximumEntriesToMerge",)),
    Axis("merge-queue-max-build", ("maximumEntriesToBuild",)),
    Axis("merge-queue-min-wait-seconds", ("minimumEntriesToMergeWaitTime",)),
    Axis("merge-queue-check-timeout-seconds", ("checkResponseTimeout",)),
)


def check_queue_settings(decl: Json, root: Path, repo: str, branch: str, report: Report) -> None:
    """Compare the queue's settings, fetched once and compared field by field.

    Compared only when a queue exists. When it does not, the presence check has already
    said so, and seven "actual: none" lines would bury that one finding. A failed fetch
    is skipped the same way.
    """
    owner, name = repo.split("/", 1)[0], repo.rsplit("/", 1)[-1]
    fields = " ".join(axis.path[0] for axis in _QUEUE_AXES)
    selection = f'mergeQueue(branch:"{branch}"){{ configuration {{ {fields} }} }}'
    query = f'{{ repository(owner:"{owner}",name:"{name}"){{ {selection} }} }}'
    result = gh(
        root, "api", "graphql", "-f", f"query={query}", "--jq", ".data.repository.mergeQueue.configuration // empty"
    )
    if not result.stdout:
        return
    config = Json.parse(result.stdout)
    if config is None:
        report.cannot_read(f"merge queue settings on {branch}: the answer is not JSON")
        return
    for axis in _QUEUE_AXES:
        want = decl.declared(axis.key)
        if want is None:
            continue
        have = config.at(*axis.path).alt("")
        if want != have:
            report.drift(f"merge queue setting {axis.key}: declared {want}, actual {have or 'none'}")


# The merge-commit button is standardised off because the queue merges by REBASE, and a
# pull request whose branch carries a merge commit cannot be rebased: the queue rejects it.
# `required-linear-history` does not cover it, since it guards `main`, not a pull request's
# own branch, and the button is what puts one there — merging a stacked pull request into its
# parent's branch, for one. Squash and rebase both keep a branch rebasable, so they are left
# to each repo.
def check_merge_commit_button(decl: Json, root: Path, repo: str, report: Report) -> None:
    """Compare the repository's merge-commit setting with the declaration.

    A repository setting, not branch protection: it is in neither payload above. The raw
    payload is read, and a payload without the field is unreadable rather than `false`:
    an absent setting is not a disabled one.
    """
    want = decl.declared("allow-merge-commit")
    if want is None:
        return
    result = gh(root, "api", f"repos/{repo}")
    payload = Json.parse(result.stdout) if result.returncode == 0 else None
    if payload is None or not payload.has("allow_merge_commit"):
        report.cannot_read("allow-merge-commit: cannot read the repository's merge settings")
        return
    have = payload.at("allow_merge_commit").alt("false")
    if want != have:
        report.drift(f"allow-merge-commit: declared {want}, actual {have}")


def check_dependabot(decl: Json, root: Path, repo: str, report: Report) -> None:
    """Compare vulnerability alerts and paused security updates.

    Not in the protection payload, and the reason they are here at all: `paused` is
    invisible from every file AND from the repo's UI at a glance — a paused repo looks
    identical to a watched one until something calls this endpoint. It is also the entry
    with the shortest half-life measured across this estate.
    """
    want_alerts = decl.declared("vulnerability-alerts")
    if want_alerts is not None:
        # 204 is on. A 404 is two answers: "Vulnerability alerts are disabled." is off,
        # while "Not Found" is a token the endpoint tells nothing to. Only the first is a
        # value.
        result = gh(root, "api", f"repos/{repo}/vulnerability-alerts", "--silent")
        if result.returncode == 0:
            have_alerts: str | None = "true"
        elif "alerts are disabled" in result.stderr:
            have_alerts = "false"
        else:
            have_alerts = None
            report.cannot_read(f"vulnerability alerts: cannot read ({result.stderr or 'no answer'})")
        if have_alerts is not None and want_alerts != have_alerts:
            report.drift(f"vulnerability alerts: declared {want_alerts}, actual {have_alerts}")
    want_paused = decl.declared("security-updates-paused")
    if want_paused is not None:
        have_paused = gh(root, "api", f"repos/{repo}/automated-security-fixes", "--jq", ".paused").stdout
        if not have_paused:
            report.cannot_read(
                f"security updates: cannot read automated-security-fixes (declared paused={want_paused})"
            )
        elif want_paused != have_paused:
            report.drift(f"security updates paused: declared {want_paused}, actual {have_paused}")


def read_target_ids(decl: Path) -> list[str]:
    """Return the environment id of every `[[deploy.target]]` in the repo's declaration, sorted and distinct.

    The anchor of the environment comparison: the environments a repo is held to are the
    ones its own targets deploy to, so a repo that deploys nothing is asked about none, and
    nothing here needs the base. A target that does not name its environment as text cannot
    be anchored, and that is a declaration that was not read, not an empty one: it stops
    the run with 2 like any other unreadable declaration.
    """
    if not decl.is_file():
        return []
    try:
        with decl.open("rb") as fh:
            targets = tomllib.load(fh).get("deploy", {}).get("target", [])
        ids = {
            f"{target['client']}-{target['environment']}" if target.get("client") else target["environment"]
            for target in targets
        }
        if not all(isinstance(identifier, str) and identifier for identifier in ids):
            raise TypeError(ids)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print(f"platform-check: cannot read the [[deploy.target]] tables of {DECL}.", file=sys.stderr)
        raise Finish(2) from None
    return sorted(ids)


def environment_standard(identifier: str, decl: Json) -> Json:
    """Return one environment's declaration: its class's standard, overlaid by the repo's own entry."""
    standard = _SHARED_ENVIRONMENT if identifier in _SHARED_ENVIRONMENT_IDS else _CLIENT_ENVIRONMENT
    override = decl.at("environments", identifier)
    return Json(standard).merged(override) if isinstance(override.value, dict) else Json(standard)


def branch_policy(environment: Json) -> str | None:
    """Name an environment's deployment branch policy, or None when it cannot be read.

    GitHub always sends the key, null for "any branch". An absent key is a payload that
    lacks the field, which says nothing about the policy rather than that there is none.
    """
    if not environment.has("deployment_branch_policy"):
        return None
    policy = environment.at("deployment_branch_policy")
    if policy.value is None:
        return "any"
    if policy.at("protected_branches").value is True:
        return "protected"
    if policy.at("custom_branch_policies").value is True:
        return "custom"
    return None


def environment_actual(environment: Json) -> dict[str, str | None]:
    """Read back, as text, each property an Environment can express; None for one the payload does not carry.

    A missing or non-list `protection_rules` is not an environment with no rule: reading it
    that way would pass an environment whose reviewers this run could not see.
    """
    listing = environment.at("protection_rules")
    policy = branch_policy(environment)
    if not isinstance(listing.value, list):
        return dict.fromkeys(("required-reviewers", "prevent-self-review", "wait-timer")) | {
            "deployment-branch-policy": policy
        }
    rules = listing.items()
    reviewer_rules = [rule for rule in rules if rule.at("type").value == "required_reviewers"]
    timers = [rule.at("wait_timer").value for rule in rules if rule.at("type").value == "wait_timer"]
    return {
        "required-reviewers": str(sum(len(rule.at("reviewers").items()) for rule in reviewer_rules)),
        "prevent-self-review": "true"
        if any(rule.at("prevent_self_review").value is True for rule in reviewer_rules)
        else "false",
        "wait-timer": str(timers[0]) if timers else "0",
        "deployment-branch-policy": policy,
    }


def read_environments(root: Path, repo: str, report: Report) -> dict[str, Json] | None:
    """Return the repo's environments by name, or None after reporting that they could not be read.

    A failed call, a body that is not JSON and a page shorter than the total are each an
    unreadable axis: a token the endpoint tells nothing to answers 403 or 404, which looks
    exactly like "no environments", and reading it that way would report every declared
    environment as missing, or, worse, none of them as drifted.
    """
    result = gh(root, "api", f"repos/{repo}/environments?per_page=100")
    payload = Json.parse(result.stdout) if result.returncode == 0 else None
    listing = payload.at("environments") if payload is not None else None
    if payload is None or listing is None or not isinstance(listing.value, list):
        report.cannot_read(f"environments: cannot read ({result.stderr or 'no usable answer'})")
        return None
    environments = listing.items()
    if payload.at("total_count").value != len(environments):
        report.cannot_read("environments: the answer is a partial page, so none is compared")
        return None
    return {environment.at("name").text(): environment for environment in environments}


def check_environments(decl: Json, root: Path, repo: str, targets: list[str], report: Report) -> None:
    """Compare every environment the repo deploys to, or declares an entry for, with its standard.

    An entry in `[platform.environments]` that matches no target is compared too: the
    environment it names must exist, so a misspelt id is a finding instead of a
    declaration nothing reads.
    """
    overrides = decl.at("environments").value
    identifiers = sorted({*targets, *(overrides if isinstance(overrides, dict) else {})})
    if not identifiers:
        print("platform-check: no deploy target, so no environment is compared.")
        return
    environments = read_environments(root, repo, report)
    if environments is None:
        return
    for identifier in identifiers:
        environment = environments.get(identifier)
        if environment is None:
            report.drift(f"environment {identifier}: the repository has no such environment")
            continue
        want, have = environment_standard(identifier, decl), environment_actual(environment)
        for key, actual in have.items():
            if actual is None:
                report.cannot_read(f"environment {identifier}: {key} has a shape GitHub does not document")
                continue
            expected = want.declared(key)
            if expected is not None and expected != actual:
                report.drift(f"environment {identifier}: {key}: declared {expected}, actual {actual}")


# Every comparison above asks "is what we declared actually set". This asks the opposite,
# and it is the half that was missing: what is set that nobody declared? An EXEMPTION does
# not flip any boolean — `required-reviews` stays 1, `enforce-admins` stays true — it just
# quietly stops applying to someone.
#
# Same inversion as `.dockyardignore`: everything is reported unless something says it is
# allowed. The default allows nothing, so an exemption has to be written down where a
# reviewer sees it, with its reason, rather than living only in a settings page.
_BYPASS = (_REVIEWS, "bypass_pull_request_allowances")
_EXEMPTIONS = (
    Exemption("allowed-bypass-users", (*_BYPASS, "users"), "login", "users allowed to bypass pull-request review"),
    Exemption("allowed-bypass-teams", (*_BYPASS, "teams"), "slug", "teams allowed to bypass pull-request review"),
    Exemption("allowed-bypass-apps", (*_BYPASS, "apps"), "slug", "apps allowed to bypass pull-request review"),
    Exemption(
        "allowed-dismissal-users",
        (_REVIEWS, "dismissal_restrictions", "users"),
        "login",
        "users allowed to dismiss reviews",
    ),
    Exemption("allowed-push-users", ("restrictions", "users"), "login", "users allowed to push directly"),
    Exemption("allowed-push-teams", ("restrictions", "teams"), "slug", "teams allowed to push directly"),
    Exemption("allowed-push-apps", ("restrictions", "apps"), "slug", "apps allowed to push directly"),
)


def check_exemptions(decl: Json, protection: Json, report: Report) -> None:
    """Report every principal the protection exempts that the declaration does not allow."""
    for exemption in _EXEMPTIONS:
        allowed = Counter(item.text() for item in decl.at(exemption.key).items())
        actual = Counter(p.at(exemption.leaf).text() for p in protection.at(*exemption.path).items())
        extra = sorted((actual - allowed).elements())
        if extra:
            report.drift(f"{exemption.label} present but not declared in [platform]: {','.join(extra)}")


def run(root: Path) -> int:
    """Compare the platform with the declaration and return the exit status."""
    if not root.is_dir():
        print(f"platform-check: cannot enter {root}: not a directory", file=sys.stderr)
        return 1
    decl = effective_declaration(read_platform(root / DECL))
    targets = read_target_ids(root / DECL)
    repo = repository(root)
    branch = decl.declared("branch") or ""
    print(f"platform-check: {repo}, branch {branch}")
    protection = read_protection(root, repo, branch)
    report = Report()
    check_required_checks(decl, protection, report)
    check_scalars(decl, protection, report)
    check_queue_presence(decl, root, repo, branch, report)
    check_queue_settings(decl, root, repo, branch, report)
    check_merge_commit_button(decl, root, repo, report)
    check_dependabot(decl, root, repo, report)
    check_environments(decl, root, repo, targets, report)
    # Proven by this run rather than listed. Reading branch protection needs the App's
    # token (GITHUB_TOKEN would have exited 2 above), and that token can only have been
    # minted with both the variable and the secret — so reaching this line is the whole
    # finding. Listing them instead was wrong twice: secret NAMES need the Secrets
    # permission, which the App does not hold, and the check's token is scoped to
    # administration and contents, so the listing failed and read as "absent" on a repo
    # where both plainly existed.
    print(
        "platform-check: App credentials GH_APP_ID and GH_APP_PRIVATE_KEY are defined and valid"
        " — this run read the protection with the token they minted."
    )
    check_exemptions(decl, protection, report)
    return finish(report)


def finish(report: Report) -> int:
    """Print the closing verdict and return the exit status."""
    if report.drifted:
        print(f"platform-check: the platform has drifted from {DECL}'s [platform] declaration.", file=sys.stderr)
        return 1
    if report.unreadable:
        print("platform-check: no drift, but at least one axis could not be read — not checkable.", file=sys.stderr)
        return 2
    print("platform-check: every declared property matches.")
    return 0


def main(argv: list[str]) -> int:
    """Run the check for the repo root in argv[0] (default: the current directory)."""
    # A runner's stdout is a pipe, which Python block-buffers: lines would reach the log out
    # of order with stderr, or be lost when the job is cancelled.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    root = Path(argv[0] if argv and argv[0] else Path.cwd())
    try:
        return run(root)
    except Finish as stop:
        return stop.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
