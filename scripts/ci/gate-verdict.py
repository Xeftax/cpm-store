#!/usr/bin/env python3
"""Sum every check job into the one required verdict: `CI Failure Report / CI Gate`.

Branch protection requires jobs by name, and the set of checks differs per repo and over
time, so one job with a fixed name reads them all and is the only required check. This is
that job's rule, kept out of `_gate.yml` so it can be run and tested as a script.

Reads, from the environment, what `_gate.yml` threads through:

- `NEEDS_JSON`: `toJSON(needs)` from the caller — each check job's `result` and its
  `_check.yml` outputs (`result`, `blocking`, and `unavailable`: why a check could not be
  verified, blank when it could).
- `MODES_JSON`: the per-trigger modes `dockyard sync` rendered into `ci.yml`, plus each
  check's cron `schedule`. Rendered statically because a skipped job has no outputs: the
  mode a job would have run in cannot be read back from the job.
- `EVENT`, `EVENT_SCHEDULE`, `DISPATCH_CHECK`: which trigger this run is, which cron fired,
  and which check a `workflow_dispatch` asked for.

Red exactly when a check whose mode on this event is `block`, `commit` or `pr` did not end
green with `blocking=false`. A blank anywhere on such a check is red too: a cancelled job
writes no output, and "no verdict" must never read as a pass. An `ignore` check never
turns it red, and one that failed is still reported, marked non-blocking.

With `--report <path>`, writes the PR comment body there instead (empty when there is
nothing to report) and always exits 0 — the comment is a courtesy, never the gate.
"""

import json
import os
import sys
from pathlib import Path
from typing import NamedTuple

BLOCKING_MODES = frozenset({"block", "commit", "pr"})
# The one line that finds this comment again on the next run, to update or delete it.
COMMENT_MARKER = "<!-- dockyard-ci-gate -->"


MAX_REASON = 300


def one_line(reason: str) -> str:
    """Return `reason` safe for a table cell: one line, no pipe, link, code span, mention or markup, and bounded.

    It comes from a workflow of the repo's, and ends up in a comment on a pull request.
    """
    flat = " ".join(reason.split())[:MAX_REASON]
    # Backslash first, so a `\|` in the reason cannot cancel the escape added for its pipe. A
    # joiner after `@` keeps the text and drops the mention; escaped brackets and backticks
    # leave no link or code span.
    escaped = flat.replace("\\", "\\\\").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for char in "|`[]":
        escaped = escaped.replace(char, "\\" + char)
    return escaped.replace("@", "@\u200d")


class Finding(NamedTuple):
    """One check that did not end green on this run."""

    check: str
    mode: str
    detail: str
    blocking: bool


def effective_mode(modes: dict[str, str], check: str, event: str, schedule: str, dispatched: str) -> str:
    """Return the mode `check` ran in on this event; `off` when this event does not run it.

    A schedule event runs only the checks whose own cron fired, and a dispatch only the one
    it names — every other check is legitimately skipped, not failed.
    """
    if event in {"pull_request", "merge_group", "push"}:
        return modes.get(event, "off")
    if event == "schedule":
        return modes.get("cron", "off") if modes.get("schedule") == schedule else "off"
    if event == "workflow_dispatch":
        # `workflow_dispatch` is rendered only when the check sets it; a manual run falls back to `cron`.
        return (modes.get("workflow_dispatch") or modes.get("cron", "off")) if check == dispatched else "off"
    return "off"


def findings(
    needs: dict[str, dict[str, object]],
    modes: dict[str, dict[str, str]],
    event: str,
    schedule: str = "",
    dispatched: str = "",
) -> list[Finding]:
    """List every check that did not end green, blocking or not, in the rendered order."""
    found: list[Finding] = []
    for check, check_modes in modes.items():
        mode = effective_mode(check_modes, check, event, schedule, dispatched)
        if mode == "off":
            continue
        job = needs.get(check, {})
        raw_outputs = job.get("outputs")
        outputs = raw_outputs if isinstance(raw_outputs, dict) else {}
        job_result = str(job.get("result") or "")
        check_result = str(outputs.get("result") or "")
        blocking = str(outputs.get("blocking") or "")
        green_for_the_gate = job_result == "success" and blocking == "false"
        detail = f"job {job_result or 'never reported'}, check {check_result or 'no verdict'}"
        if reason := one_line(str(outputs.get("unavailable") or "")):
            detail += f" — could not be verified: {reason}"
        if mode in BLOCKING_MODES and not green_for_the_gate:
            found.append(Finding(check, mode, detail, blocking=True))
        elif check_result != "success" or job_result != "success":
            found.append(Finding(check, mode, detail, blocking=False))
    return found


def report(found: list[Finding], run_url: str) -> str:
    """Render the PR comment body, or an empty string when there is nothing to say."""
    if not found:
        return ""
    lines = [COMMENT_MARKER, "## CI checks that did not pass", "", "| Check | Mode | Result |", "| --- | --- | --- |"]
    for finding in found:
        mode = finding.mode if finding.blocking else f"{finding.mode} (non-blocking)"
        lines.append(f"| `{finding.check}` | {mode} | {finding.detail} |")
    if run_url:
        lines += ["", f"Logs: {run_url}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """Print the verdict and exit 1 on a blocking finding; or write the report and exit 0."""
    needs = json.loads(os.environ.get("NEEDS_JSON") or "{}")
    modes = json.loads(os.environ.get("MODES_JSON") or "{}")
    found = findings(
        needs,
        modes,
        os.environ.get("EVENT", ""),
        os.environ.get("EVENT_SCHEDULE", ""),
        os.environ.get("DISPATCH_CHECK", ""),
    )
    if len(argv) == 2 and argv[0] == "--report":  # noqa: PLR2004 — the flag and its path
        Path(argv[1]).write_text(report(found, os.environ.get("RUN_URL", "")))
        return 0
    for finding in found:
        label = "FAILED" if finding.blocking else "failed, non-blocking"
        print(f"{finding.check} ({finding.mode}): {label} — {finding.detail}")
    if any(finding.blocking for finding in found):
        return 1
    print("Every blocking check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
