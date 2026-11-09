#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Turn a bandit or semgrep JSON report into a Markdown summary and a CI verdict.

Run by `sast-python.sh` (bandit) and `sast-typescript.sh` (semgrep), which own the scan
itself and the "no report was written" guard; this only reads a report that exists.
Writes the summary file, prints the same text to stdout, and with `--verdict` prints
`::error::` to stderr and exits 1 when at least one finding carries the tool's top
severity. Without `--verdict` a report with findings still exits 0.

The summary layout is a contract with the PR comment that embeds it, and the output is
byte-identical to the jq program this replaced.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import NamedTuple


class Finding(NamedTuple):
    """One report row, already rendered to the strings the table shows."""

    severity: str
    rule: str
    location: str
    issue: str


class ToolSpec(NamedTuple):
    """Where a tool keeps each field in its JSON, and how its summary is labelled."""

    name: str
    severities: tuple[str, str, str]  # top, middle, bottom
    rule_header: str
    fields: tuple[tuple[str, ...], ...]  # JSON path of severity, rule, path, line, message
    strip_dot_slash: bool  # bandit reports "./pkg/mod.py"; semgrep reports "pkg/mod.py"


TOOLS = {
    "bandit": ToolSpec(
        "bandit",
        ("HIGH", "MEDIUM", "LOW"),
        "Test",
        (("issue_severity",), ("test_id",), ("filename",), ("line_number",), ("issue_text",)),
        strip_dot_slash=True,
    ),
    "semgrep": ToolSpec(
        "semgrep",
        ("ERROR", "WARNING", "INFO"),
        "Rule",
        (
            ("extra", "severity"),
            ("check_id",),
            ("path",),
            ("start", "line"),
            ("extra", "message"),
        ),
        strip_dot_slash=False,
    ),
}


def field(node: object, path: tuple[str, ...]) -> object:
    """Walk `path` through nested JSON objects; a missing step yields None, as jq's `.a.b` does."""
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def interpolate(value: object) -> str:
    """Render a JSON value the way jq's string interpolation does (null, bare numbers)."""
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def to_finding(tool: ToolSpec, result: object) -> Finding:
    """Read one report result into the row it renders as."""
    severity, rule, path, line, message = (field(result, p) for p in tool.fields)
    filename = interpolate(path)
    if tool.strip_dot_slash:
        filename = filename.removeprefix("./")
    issue = interpolate(message).replace("|", " ").replace("\n", " ")
    return Finding(interpolate(severity), interpolate(rule), f"{filename}:{interpolate(line)}", issue)


def parse_report(tool: ToolSpec, text: str) -> list[Finding]:
    """Parse a report; raise ValueError when it is not JSON or has no results array."""
    results = field(json.loads(text), ("results",))
    if not isinstance(results, list):
        raise ValueError("report has no 'results' array")
    return [to_finding(tool, r) for r in results]


def render(tool: ToolSpec, findings: list[Finding]) -> str:
    """Build the Markdown summary: a counts line, then a severity-sorted table or 'No findings.'."""
    top, middle, bottom = tool.severities
    n = {label: sum(f.severity == label for f in findings) for label in tool.severities}
    lines = [
        f"**{n[top]} {top.lower()} · {n[middle]} {middle.lower()} · {n[bottom]} {bottom.lower()}**",
        "",
    ]
    if not findings:
        lines.append("No findings.")
    else:
        rank = {top: 0, middle: 1}
        lines.append(f"| Severity | {tool.rule_header} | Location | Issue |")
        lines.append("| :-- | :-- | :-- | :-- |")
        # sorted() is stable, like jq's sort_by: findings of one severity keep report order.
        ordered = sorted(findings, key=lambda f: rank.get(f.severity, 2))
        lines.extend(f"| {f.severity} | `{f.rule}` | `{f.location}` | {f.issue} |" for f in ordered)
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """Write the summary file, echo it, and apply the verdict when asked."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", choices=sorted(TOOLS), required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--verdict", action="store_true")
    args = parser.parse_args(argv)
    tool = TOOLS[args.tool]

    try:
        findings = parse_report(tool, args.report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"::error::{tool.name}: unreadable JSON report {args.report}: {exc}", file=sys.stderr)
        return 1
    summary = render(tool, findings)
    args.summary.write_text(summary, encoding="utf-8")
    sys.stdout.buffer.write(summary.encode("utf-8"))
    sys.stdout.buffer.flush()

    top = tool.severities[0]
    blocking = sum(f.severity == top for f in findings)
    if args.verdict and blocking:
        print(f"::error::{tool.name}: {blocking} {top} finding(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
