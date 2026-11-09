#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
r"""Mechanical operations on a repo's GitHub Project board, for the board-sync skill and `_board.yml`.

The skill keeps the judgment (which PR maps to which issue) in the model; this script owns
the deterministic, error-prone I/O: the scan window, the inventory, an item's current
status, and a Status transition with its safety rules written in one place. A local
session and CI run the same file.

    window                       THRESHOLD (YYYY-MM-DD) from the ledger issue's last comment
    scan [THRESHOLD]             inventory: PRs (all + merged), open issues, active branches
    board-list                   "<status>\\t#<num>\\t<state>\\t<title>" for every board item
    status <issue>               "<item_id>\\t<current_status>"; empty item id = not on the board
    onboard <issue>              add to the board; Status=Todo and Prio=now only if unset
    apply <issue> <signal>       forward-only move, signal = open|draft|merged; never sets Done
    audit-inventory              "<status>\\t<area>\\t<touches>\\t#<num>\\t<title>" per open board issue
    area-dirty <sha> -- <path…>  exit 0 when origin/main moved under <path…> since <sha>, else 1
    ledger-read                  the audit ledger JSON from the ledger issue's body
    ledger-write <file>          splice <file>'s JSON into the ledger issue's body
    minimize-comment <node-id>   hide a comment as OUTDATED
    minimize-prior-reports       collapse every audit report on the ledger issue but the newest

    enabled                      exit 0 when `dockyard.toml` sets `[board] project_number`, else 1

Which board, ledger issue and forward-only status order are per-repo facts, read from the
`[board]` table of `dockyard.toml` at the repo root, the status order defaulting to
`DEFAULT_STATUS_ORDER` below. The repository comes from `GITHUB_REPOSITORY`, or from `gh repo view`
in a local session; the board's organisation is its owner. Field and option ids are never
written down: they are resolved by name against the live board, so the script runs
unmodified on any repo's board. Requires an authenticated `gh`, and `git` for `scan` and
`area-dirty`.
"""

import json
import os
import re
import subprocess
import sys
import time
import tomllib
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, NamedTuple

CONFIG_PATH = Path("dockyard.toml")
# The forward-only order of the Status column when a repo does not set its own. This script
# runs in repos that no longer receive `dockyard.base.toml`, so it carries the default; the
# base stays the declaration and a test holds the two equal.
DEFAULT_STATUS_ORDER = ["To investigate", "Todo", "In Progress", "Plan Review", "Code Review", "Done?", "Done"]
LEDGER_MARK = "<!-- board-audit-ledger -->"
REPORT_MARK = "<!-- board-audit-report -->"
EMPTY_LEDGER = '{"areas":{},"issues":{}}'
# A merged PR stops at `Done?`: closing an issue is a human's call.
SIGNAL_TARGET = {"open": "Code Review", "draft": "In Progress", "merged": "Done?"}
USAGE = (
    "usage: board_sync.py {window|scan [THRESHOLD]|board-list|status <issue>|onboard <issue>|"
    "apply <issue> open|draft|merged|audit-inventory|area-dirty <sha> -- <path…>|ledger-read|"
    "ledger-write <file>|minimize-comment <node-id>|minimize-prior-reports|enabled}"
)

type Json = Any

_FIELDS = "fieldValues(first: 20) { nodes { ... on ProjectV2ItemFieldSingleSelectValue { field { ... on ProjectV2SingleSelectField { name } } name } } }"  # noqa: E501 — one GraphQL fragment
_ITEMS_QUERY = """
query($org: String!, $num: Int!, $c: String) {
  organization(login: $org) { projectV2(number: $num) {
    items(first: 100, after: $c) {
      pageInfo { hasNextPage endCursor }
      nodes { content { %s } %s }
    } } } }"""


class BoardError(Exception):
    """A failure the caller reports on stderr, with the exit status it maps to."""

    def __init__(self, message: str, status: int = 1) -> None:
        """Keep the exit status beside the message."""
        super().__init__(message)
        self.status = status


class Config(NamedTuple):
    """The `[board]` table of `dockyard.toml` plus the repository it runs in, validated."""

    repo: str
    org: str
    project_number: int
    ledger_issue: int
    status_order: list[str]

    @property
    def repo_name(self) -> str:
        """The repository name without its owner."""
        return self.repo.partition("/")[2]


def _board_table(path: Path) -> dict[str, Any]:
    """Return the `[board]` table of one TOML file; empty when the file or the table is absent."""
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        board = tomllib.load(f).get("board", {})
    return board if isinstance(board, dict) else {}


def board_enabled(path: Path = CONFIG_PATH) -> bool:
    """Whether the repo opts into board automation: `[board] project_number` is set."""
    return "project_number" in _board_table(path)


def current_repo() -> str:
    """`owner/name` of the repository: `GITHUB_REPOSITORY` in CI, `gh repo view` in a local session."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        repo = json.loads(run("gh", "repo", "view", "--json", "nameWithOwner"))["nameWithOwner"]
    return str(repo)


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read `[board]` from `path`, `status_order` defaulting to the script's own, naming the first missing key."""
    table = _board_table(path)
    if "project_number" not in table:
        message = (
            f"ERROR: {path} sets no [board] project_number (run from the repo root).\n"
            "Board automation needs a [board] table in dockyard.toml declaring project_number and\n"
            "ledger_issue; status_order has a default."
        )
        raise BoardError(message)
    # The merge rule of dockyard.base_config for these keys: an array replaces whole.
    table = {"status_order": DEFAULT_STATUS_ORDER, **table}
    for key in ("project_number", "ledger_issue", "status_order"):
        if not table.get(key):
            raise BoardError(f"ERROR: {path} [board] is missing '{key}'.")
    for key in ("project_number", "ledger_issue"):
        if not str(table[key]).isdigit():
            raise BoardError(f"ERROR: {path} [board]: '{key}' must be a number, got {table[key]!r}.")
    repo = current_repo()
    return Config(
        repo,
        repo.partition("/")[0],
        int(table["project_number"]),
        int(table["ledger_issue"]),
        list(table["status_order"]),
    )


def run(*args: str, stdin: str | None = None, check: bool = True) -> str:
    """Run a command and return its stdout; the one place the script shells out."""
    result = subprocess.run(args, input=stdin, capture_output=True, text=True, check=False)  # noqa: S603 — fixed gh/git argv
    if check and result.returncode != 0:
        raise BoardError(result.stderr.strip() or f"{args[0]} exited {result.returncode}", result.returncode)
    return result.stdout


def graphql(query: str, **variables: str | int | None) -> Json:
    """One `gh api graphql` call; `-F` so ints stay ints and None becomes JSON null."""
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        args += ["-F", f"{key}={'null' if value is None else value}"]
    return json.loads(run(*args))


def _field_value(node: Json, field: str) -> str | None:
    """Return the named single-select value on a board item, None when unset."""
    for value in node.get("fieldValues", {}).get("nodes", []):
        if value and value.get("field", {}).get("name") == field:
            return str(value["name"])
    return None


def _board_items(cfg: Config, content: str) -> list[Json]:
    """Every item of the board, paginated: one capped page would silently drop the rest."""
    items: list[Json] = []
    cursor: str | None = None
    while True:
        page = graphql(_ITEMS_QUERY % (content, _FIELDS), org=cfg.org, num=cfg.project_number, c=cursor)
        block = page["data"]["organization"]["projectV2"]["items"]
        items += block["nodes"]
        if not block["pageInfo"]["hasNextPage"]:
            return items
        cursor = block["pageInfo"]["endCursor"]


# ponytail: resolved once per process, not cached across invocations like the shell version's
# TSV file with a TTL; one extra GraphQL call per subcommand, add a file cache if rate matters.
@cache
def _fields(org: str, number: int) -> tuple[str, dict[str, tuple[str, dict[str, str]]]]:
    """(project id, field name -> (field id, option name -> option id)) for single-select fields.

    The options come back in the order last arranged in the UI, not the workflow's forward
    order, so rank never comes from here: it is `status_order` in the config.
    """
    query = """
    query($org: String!, $num: Int!) { organization(login: $org) { projectV2(number: $num) {
      id fields(first: 30) { nodes {
        ... on ProjectV2SingleSelectField { id name options { id name } }
        ... on ProjectV2Field { id name } } } } } }"""
    project = graphql(query, org=org, num=number)["data"]["organization"]["projectV2"]
    fields = {
        f["name"]: (f["id"], {o["name"]: o["id"] for o in f["options"]})
        for f in project["fields"]["nodes"]
        if f and "options" in f
    }
    return project["id"], fields


def _option_id(cfg: Config, field: str, option: str) -> tuple[str, str]:
    """(field id, option id) for a single-select field's named option."""
    _, fields = _fields(cfg.org, cfg.project_number)
    field_id, options = fields.get(field, ("", {}))
    if option not in options:
        raise BoardError(f"board has no option '{option}' on field '{field}'")
    return field_id, options[option]


def status_rank(cfg: Config, name: str | None) -> int:
    """Position in the forward-only order; -1 for unset or unknown, which ranks below everything."""
    return cfg.status_order.index(name) if name in cfg.status_order else -1


def read_field(cfg: Config, issue: str, field: str) -> tuple[str, str]:
    """(item id, value) of a named field on the issue's item on this board; ("", "") if not on it."""
    query = f"""
    query($owner: String!, $name: String!, $num: Int!) {{ repository(owner: $owner, name: $name) {{
      issue(number: $num) {{ projectItems(first: 5) {{ nodes {{ id project {{ number }} {_FIELDS} }} }} }} }} }}"""
    data = graphql(query, owner=cfg.org, name=cfg.repo_name, num=int(issue))
    for node in data["data"]["repository"]["issue"]["projectItems"]["nodes"]:
        if node["project"]["number"] == cfg.project_number:
            return node["id"], _field_value(node, field) or ""
    return "", ""


def set_field(cfg: Config, item: str, field: str, option: str) -> None:
    """One single-select write. No policy here: callers own it."""
    project_id, _ = _fields(cfg.org, cfg.project_number)
    field_id, option_id = _option_id(cfg, field, option)
    mutation = """
    mutation($item: ID!, $field: ID!, $opt: String!, $project: ID!) {
      updateProjectV2ItemFieldValue(input: { projectId: $project fieldId: $field
        itemId: $item value: { singleSelectOptionId: $opt } }) { projectV2Item { id } } }"""
    graphql(mutation, item=item, field=field_id, opt=option_id, project=project_id)


def cmd_window(cfg: Config) -> str:
    """Return the date in the ledger issue's last comment heading, else 24 hours ago (UTC)."""
    try:
        comments = json.loads(
            run("gh", "issue", "view", str(cfg.ledger_issue), "--repo", cfg.repo, "--json", "comments")
        )
        heading = comments["comments"][-1]["body"].split("\n")[0]
    except (BoardError, IndexError, KeyError):
        heading = ""
    if m := re.search(r"\d{4}-\d{2}-\d{2}", heading):
        return m[0]
    return (datetime.now(UTC) - timedelta(hours=24)).strftime("%Y-%m-%d")


def cmd_scan(cfg: Config, threshold: str | None) -> str:
    """Print the PR-driven inventory the skill matches against the board."""
    threshold = threshold or cmd_window(cfg)
    pr_fields = "number,title,state,headRefName,author,body,mergedAt,isDraft,closingIssuesReferences"
    out = [f"=== THRESHOLD: {threshold} ===", "=== PRs (updated>=threshold, all states) ==="]
    out.append(
        run(
            "gh",
            "pr",
            "list",
            "--repo",
            cfg.repo,
            "--search",
            f"updated:>={threshold}",
            "--state",
            "all",
            "--limit",
            "100",
            "--json",
            pr_fields,
        ).rstrip()
    )
    out.append("=== PRs (merged>=threshold) ===")
    merged_fields = pr_fields.replace("isDraft,", "")
    out.append(
        run(
            "gh",
            "pr",
            "list",
            "--repo",
            cfg.repo,
            "--search",
            f"merged:>={threshold}",
            "--state",
            "merged",
            "--limit",
            "100",
            "--json",
            merged_fields,
        ).rstrip()
    )
    out.append("=== open issues ===")
    out.append(
        run(
            "gh",
            "issue",
            "list",
            "--repo",
            cfg.repo,
            "--state",
            "open",
            "--limit",
            "150",
            "--json",
            "number,title,body,labels,assignees",
        ).rstrip()
    )
    out.append("=== active branches (log since threshold) ===")
    run("git", "fetch", "--all", "--quiet", check=False)
    for ref in run("git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/").split():
        if ref in ("origin/HEAD", "origin/main", "origin") or ref.startswith("origin/dependabot/"):
            continue
        if run("git", "log", f"--since={threshold}", "--oneline", ref, check=False).strip():
            out.append(ref.removeprefix("origin/"))
    return "\n".join(out)


def cmd_board_list(cfg: Config) -> str:
    """List every board item with its Status."""
    items = _board_items(cfg, "... on Issue { number title state } ... on PullRequest { number title state }")
    return "\n".join(
        f"{_field_value(n, 'Status') or '—'}\t#{c['number']}\t{c['state']}\t{c['title']}"
        for n in items
        if (c := n.get("content")) and c.get("number") is not None
    )


def cmd_status(cfg: Config, issue: str) -> str:
    """Return the issue's board item and Status, empty when it is not on the board."""
    item, value = read_field(cfg, issue, "Status")
    return f"{item}\t{value}" if item else ""


def cmd_onboard(cfg: Config, issue: str, retries: int = 3, pause: float = 2) -> str:
    """Bring a new issue onto the board without ever overriding a value a human set."""
    item, status = "", ""
    for _ in range(retries):  # item-add lags right after an issue is created
        run(
            "gh",
            "project",
            "item-add",
            str(cfg.project_number),
            "--owner",
            cfg.org,
            "--url",
            f"https://github.com/{cfg.repo}/issues/{issue}",
            check=False,
        )
        item, status = read_field(cfg, issue, "Status")
        if item:
            break
        time.sleep(pause)
    if not item:
        raise BoardError(f"#{issue} add failed — not on board")
    if not status:
        set_field(cfg, item, "Status", "Todo")
        status = "Todo (set)"
    _, prio = read_field(cfg, issue, "Prio")
    if not prio:
        set_field(cfg, item, "Prio", "now")
        prio = "now (set)"
    return f"#{issue} onboarded — Status='{status}' Prio='{prio}'"


def cmd_apply(cfg: Config, issue: str, signal: str) -> str:
    """Move an issue forward to its signal's target; a regression or an equal status is a no-op."""
    if signal not in SIGNAL_TARGET:
        raise BoardError(f"unknown signal: {signal} (want open|draft|merged)", 2)
    target = SIGNAL_TARGET[signal]
    item, current = read_field(cfg, issue, "Status")
    if not item:
        add = f"gh project item-add {cfg.project_number} --owner {cfg.org} --url https://github.com/{cfg.repo}/issues/{issue}"
        raise BoardError(f"#{issue} NOT ON BOARD — add first: {add}")
    if status_rank(cfg, current) >= status_rank(cfg, target):
        return f"#{issue} no-op — already '{current}' (>= target '{target}')"
    set_field(cfg, item, "Status", target)
    return f"#{issue} '{current}' -> '{target}'"


def cmd_audit_inventory(cfg: Config) -> str:
    """Per open board issue, its Status, Area and touches:* labels: the audit's grouping input."""
    items = _board_items(cfg, "... on Issue { number title state labels(first: 30) { nodes { name } } }")
    lines = []
    for n in items:
        c = n.get("content") or {}
        if c.get("number") is None or c.get("state") != "OPEN":
            continue
        touches = ",".join(label["name"] for label in c["labels"]["nodes"] if label["name"].startswith("touches:"))
        status, area = _field_value(n, "Status") or "—", _field_value(n, "Area") or "—"
        lines.append(f"{status}\t{area}\t{touches}\t#{c['number']}\t{c['title']}")
    return "\n".join(lines)


def cmd_area_dirty(since: str, paths: list[str]) -> int:
    """0 when origin/main has commits under `paths` since `since`; an unknown sha is always dirty."""
    run("git", "fetch", "origin", "main", "--quiet", check=False)
    if (
        not since
        or subprocess.run(  # noqa: S603 — fixed git argv
            ["git", "cat-file", "-e", f"{since}^{{commit}}"],  # noqa: S607 — git via PATH is intended
            capture_output=True,
            check=False,
        ).returncode
    ):  # noqa: S607
        return 0
    return 0 if run("git", "log", "--oneline", f"{since}..origin/main", "--", *paths, check=False).strip() else 1


def _ledger_body(cfg: Config) -> str:
    """Return the ledger issue's body; a failed read raises, so a write never starts from a guess."""
    try:
        view = run("gh", "issue", "view", str(cfg.ledger_issue), "--repo", cfg.repo, "--json", "body")
    except BoardError as error:
        raise BoardError(f"cannot read #{cfg.ledger_issue}'s body: {error}", error.status) from error
    return str(json.loads(view)["body"] or "")


def cmd_ledger_read(cfg: Config) -> str:
    """Return the JSON inside the ledger issue body's ```json fence, or an empty ledger."""
    try:
        body = _ledger_body(cfg)
    except BoardError:
        return EMPTY_LEDGER
    m = re.search(r"```json\r?\n(.*?)\r?\n?```", body, re.DOTALL)
    return m[1].strip() if m and m[1].strip() else EMPTY_LEDGER


def cmd_ledger_write(cfg: Config, file: str) -> str:
    """Keep the human intro above the marker, replace the marker and its fence with `file`."""
    path = Path(file)
    if not path.is_file():
        raise BoardError(f"ledger-write: no such file: {file}", 2)
    intro = _ledger_body(cfg).split(LEDGER_MARK)[0].rstrip("\r\n")
    note = (
        "_board-audit ledger — machine-managed (slim: Areas + actionable verdicts only). "
        "Prior states: this issue's edit history._"
    )
    body = f"{intro}\n{LEDGER_MARK}\n{note}\n\n```json\n{path.read_text()}\n```\n"
    run("gh", "issue", "edit", str(cfg.ledger_issue), "--repo", cfg.repo, "--body-file", "-", stdin=body)
    return f"ledger written to #{cfg.ledger_issue} body"


def cmd_minimize_comment(node_id: str) -> str:
    """Hide one comment as OUTDATED."""
    mutation = """
    mutation($id: ID!) { minimizeComment(input: {subjectId: $id, classifier: OUTDATED}) {
      minimizedComment { isMinimized } } }"""
    graphql(mutation, id=node_id)
    return f"minimized {node_id}"


def cmd_minimize_prior_reports(cfg: Config) -> str:
    """Collapse every audit report on the ledger issue but the newest; GitHub skips ones already hidden."""
    pages = run("gh", "api", f"repos/{cfg.repo}/issues/{cfg.ledger_issue}/comments", "--paginate", "--slurp")
    comments = [c for page in json.loads(pages) for c in page]
    ids = [c["node_id"] for c in comments if REPORT_MARK in (c.get("body") or "")][:-1]
    return "\n".join(cmd_minimize_comment(i) for i in ids) or "no prior reports to minimize"


def cmd_enabled() -> int:
    """Exit status 0 when the repo opts into the board, 1 (with one notice line) when it does not."""
    if board_enabled():
        return 0
    print("no [board] project_number in dockyard.toml: this repo declares no board", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    """Dispatch a subcommand; print its output, or its error on stderr with its exit status."""
    command, args = (argv[0], argv[1:]) if argv else ("", [])
    try:
        if command == "minimize-comment" and args:
            print(cmd_minimize_comment(args[0]))
            return 0
        if command in ("status", "onboard", "apply") and args and not args[0].isdigit():
            raise BoardError(f"{command}: issue number expected, got {args[0]!r}", 2)
        if command in ("area-dirty", "enabled"):
            since, paths = (args[0] if args else ""), [p for p in args[1:] if p != "--"]
            return cmd_enabled() if command == "enabled" else cmd_area_dirty(since, paths)
        cfg = load_config()
        handlers = {
            "window": lambda: cmd_window(cfg),
            "scan": lambda: cmd_scan(cfg, args[0] if args else None),
            "board-list": lambda: cmd_board_list(cfg),
            "status": lambda: cmd_status(cfg, args[0]),
            "onboard": lambda: cmd_onboard(cfg, args[0]),
            "apply": lambda: cmd_apply(cfg, args[0], args[1]),
            "audit-inventory": lambda: cmd_audit_inventory(cfg),
            "ledger-read": lambda: cmd_ledger_read(cfg),
            "ledger-write": lambda: cmd_ledger_write(cfg, args[0]),
            "minimize-prior-reports": lambda: cmd_minimize_prior_reports(cfg),
        }
        if command not in handlers:
            print(USAGE, file=sys.stderr)
            return 2
        output = handlers[command]()
    except BoardError as error:
        print(error, file=sys.stderr)
        return error.status
    except IndexError:
        print(USAGE, file=sys.stderr)
        return 2
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
