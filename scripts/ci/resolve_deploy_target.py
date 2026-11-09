#!/usr/bin/env python3
"""Resolve deploy targets from the `[deploy]` tables of a repo's own `dockyard.toml`.

Two modes, both reading `dockyard.toml` (or `--file`) and writing `key=value` lines to
`$GITHUB_OUTPUT`, or to stdout when that is unset, so the same command answers "what does
gxo-uat map to" at a laptop:

- resolve one target: `TARGET_ID` (a canonical id such as `gxo-uat` or `dev`) or
  `TARGET_CLIENT` + `TARGET_ENVIRONMENT`, and optionally `TARGET_COMPONENT` (default
  `default`). One output line per field, plus `values=<json>` with the typed whole.
- list targets: `--list` (or `TARGET_LIST=true`), narrowed by `LIST_WHERE` / `--where key=value` (every filter must
  match). Emits `targets=<json array>`, `matrix=<{"include": [...]}>` and `count=`, so a
  caller builds `strategy.matrix` from the file instead of restating its rows.

`[deploy]` has three kinds of table beside the dispatch choices (`environments`,
`components`, which this script ignores) and a fixed merge order, least specific first:

    [deploy.defaults]               every target
    [deploy.component.<name>]       every target of that component
    [[deploy.target]]               one environment (+ component), the lookup key

`dockyard check` and `dockyard sync` validate these tables with the same rules
(`dockyard.deploy_targets`), so a bad target stops there with its key path before it reaches a
runner. A `[[deploy.target]]` needs `environment`; `client` is optional (`dev` and `demo` have none) and
`component` defaults to `default`. Tables merge recursively, anything else is replaced. The
schema stays open on purpose: an ECS live-worker's fields and a Terraform
workspace are different sets on the same shape, and a fixed schema would force one repo's
columns onto the other. Values keep their TOML type (a list stays a list) because
`deployers = [...]` has to be one.

A [C] script, not bundled inside an action: read-only, no secrets, no mutation, and "what
account/role does gxo-uat map to" is asked during onboarding and manual ops work with no
deploy in sight.
"""

import argparse
import json
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

DEFAULT_COMPONENT = "default"
RESERVED_FIELDS = frozenset({"values", "targets", "matrix", "count"})
KEY_FIELDS = ("client", "environment", "component")

type Value = str | int | float | bool | list[Value] | dict[str, Value]
type Fields = dict[str, Value]


class ResolvedTarget(NamedTuple):
    """One [[target]], its lookup key split out and its merged fields beside it."""

    client: str
    environment: str
    component: str
    fields: Fields

    @property
    def identifier(self) -> str:
        """The canonical `<client>-<stage>` id (just the stage for a target with no client)."""
        return environment_id(self.client, self.environment)


class TargetsFileError(ValueError):
    """The `[deploy]` tables, or what asked about it, are malformed."""


def environment_id(client: str, environment: str) -> str:
    """Join a client and a stage into the canonical environment id."""
    return f"{client}-{environment}" if client else environment


def split_environment_id(identifier: str) -> tuple[str, str]:
    """Split a canonical id into (client, stage): `acme-uat` is acme/uat, `dev` has no client."""
    client, dash, stage = identifier.partition("-")
    return (client, stage) if dash else ("", identifier)


def _plain(value: object) -> Value:
    """Convert a TOML value to plain JSON-able data; the types TOML adds (dates) become strings."""
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return str(value)


def _table(document: Mapping[str, object], key: str, path: Path, parent: str = "") -> dict[str, object]:
    value = document.get(key, {})
    if not isinstance(value, dict):
        raise TargetsFileError(f"{path}: `{parent}{key}` must be a table, got {type(value).__name__}")
    return {str(name): item for name, item in value.items()}


def merge(base: Fields, override: Fields) -> Fields:
    """Merge two field sets: tables recurse, every other value is replaced whole."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        merged[key] = merge(current, value) if isinstance(current, dict) and isinstance(value, dict) else value
    return merged


def _as_fields(value: object, where: str) -> Fields:
    plain = _plain(value)
    if not isinstance(plain, dict):
        raise TargetsFileError(f"{where} must be a table")
    return plain


def load_targets(path: Path) -> list[ResolvedTarget]:
    """Read `[deploy]` from the file and return every target with defaults and its component merged in."""
    with path.open("rb") as handle:
        document = tomllib.load(handle)
    deploy = _table(document, "deploy", path)
    defaults = _as_fields(deploy.get("defaults", {}), f"{path}: [deploy.defaults]")
    components = {
        name: _as_fields(item, f"{path}: [deploy.component.{name}]")
        for name, item in _table(deploy, "component", path, "deploy.").items()
    }
    entries = deploy.get("target", [])
    if not isinstance(entries, list):
        raise TargetsFileError(
            f"{path}: `deploy.target` must be an array of tables ([[deploy.target]]), got {type(entries).__name__}"
        )

    resolved = []
    for entry in entries:
        if not isinstance(entry, dict) or "environment" not in entry:
            raise TargetsFileError(f"{path}: every [[deploy.target]] needs `environment`, got {entry!r}")
        own = _as_fields(entry, f"{path}: a [[deploy.target]]")
        client, environment = str(own.get("client", "")), str(own["environment"])
        component = str(own.get("component", DEFAULT_COMPONENT))
        fields = merge(
            merge(defaults, components.get(component, {})), {k: v for k, v in own.items() if k not in KEY_FIELDS}
        )
        reserved = sorted(RESERVED_FIELDS & fields.keys())
        if reserved:
            raise TargetsFileError(
                f"{path}: {environment_id(client, environment)}/{component} uses reserved field(s) {reserved}"
            )
        resolved.append(ResolvedTarget(client, environment, component, fields))
    return resolved


def find_target(
    targets: Sequence[ResolvedTarget], client: str, environment: str, component: str = DEFAULT_COMPONENT
) -> ResolvedTarget | None:
    """Return the first target matching (client, environment, component), or None."""
    for target in targets:
        if (target.client, target.environment, target.component) == (client, environment, component):
            return target
    return None


def describe(target: ResolvedTarget) -> Fields:
    """Flatten a target into one object: its key fields and id, then every merged field."""
    key: Fields = {
        "id": target.identifier,
        "client": target.client,
        "environment": target.environment,
        "component": target.component,
    }
    return {**target.fields, **key}


def parse_where(clauses: Sequence[str]) -> dict[str, str]:
    """Turn `key=value` clauses into a filter; a clause without `=` is an error."""
    where = {}
    for clause in clauses:
        key, equals, value = clause.partition("=")
        if not equals or not key:
            raise TargetsFileError(f"bad filter {clause!r}: expected key=value")
        where[key] = value
    return where


def render_value(value: Value) -> str:
    """Render a field for an output line: scalars as written, tables and lists as JSON."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | dict):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def list_targets(targets: Sequence[ResolvedTarget], where: Mapping[str, str]) -> list[Fields]:
    """Every target whose fields match all of `where`, compared as rendered text."""
    rows = [describe(target) for target in targets]
    return [row for row in rows if all(key in row and render_value(row[key]) == want for key, want in where.items())]


def _lines(pairs: Sequence[tuple[str, str]], *, skip_multiline: bool = False) -> str:
    """Render `key=value` output lines; a line break in a key is an error.

    A value with a line break would forge the next line. With `skip_multiline` such a field
    is left out (the caller carries it in a JSON output, which escapes the break); without
    it, one is an error: nothing else could carry it.
    """
    lines = []
    for key, value in pairs:
        if "\n" in key or "\r" in key or "=" in key:
            raise TargetsFileError(f"field name {key!r} cannot be an output name")
        if "\n" in value or "\r" in value:
            if skip_multiline:
                continue
            raise TargetsFileError(f"field {key!r} holds a line break, which an output line cannot carry")
        lines.append(f"{key}={value}\n")
    return "".join(lines)


def _emit(text: str, github_output: str | None) -> None:
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)


def _compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def _resolve_one(targets: Sequence[ResolvedTarget], env: Mapping[str, str]) -> tuple[str, str]:
    """Look up the target the environment names; return (output text, log line)."""
    if env.get("TARGET_ID"):
        client, environment = split_environment_id(env["TARGET_ID"])
    else:
        client, environment = env.get("TARGET_CLIENT", ""), env.get("TARGET_ENVIRONMENT", "")
        if not environment:
            raise TargetsFileError("name a target: TARGET_ID, or TARGET_ENVIRONMENT (+ TARGET_CLIENT)")
    component = env.get("TARGET_COMPONENT") or DEFAULT_COMPONENT
    match = find_target(targets, client, environment, component)
    if match is None:
        known = ", ".join(f"{t.identifier}/{t.component}" for t in targets)
        wanted = f"{environment_id(client, environment)}/{component}"
        raise TargetsFileError(f"No target for {wanted}. Known: {known}")

    # Two lines, for two readers. The per-field lines are what a step INSIDE the calling
    # action reads (`steps.<id>.outputs.<field>`). A composite action can only publish
    # outputs it DECLARES, statically, and an open-ended field set has no static names: so
    # the whole bag also goes out as one typed JSON output the caller reads with
    # `fromJSON`. Not $GITHUB_ENV: these keys come from a repo's own file, so a field named
    # `PATH` would overwrite the job's environment rather than be read as data.
    # A multi-line string field (a multi-line `build_args`) has no single-line form: it is
    # left out of the per-field lines and travels in `values`, where JSON escapes the break.
    pairs = [(key, render_value(value)) for key, value in match.fields.items()]
    text = _lines(pairs, skip_multiline=True) + _lines([("values", _compact(match.fields))])
    return text, f"Resolved {match.identifier}/{match.component}: {', '.join(match.fields)}"


def _list(targets: Sequence[ResolvedTarget], where: Mapping[str, str]) -> tuple[str, str]:
    rows = list_targets(targets, where)
    pairs = [("targets", _compact(rows)), ("matrix", _compact({"include": rows})), ("count", str(len(rows)))]
    return _lines(pairs), f"Listed {len(rows)} target(s)"


def build_parser() -> argparse.ArgumentParser:
    """Build the command line: the list mode, its filters, and where `dockyard.toml` is."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--file", default="dockyard.toml", help="the file holding `[deploy]` (default: dockyard.toml)")
    parser.add_argument("--list", action="store_true", help="list targets instead of resolving one")
    parser.add_argument(
        "--where", action="append", default=[], metavar="KEY=VALUE", help="only targets with this field"
    )
    return parser


def main(argv: Sequence[str], env: Mapping[str, str]) -> int:
    """Resolve or list per `argv`/`env`; print `::error::` and return 1 on a bad file or lookup."""
    args = build_parser().parse_args(argv)
    path = Path(args.file)
    listing = args.list or env.get("TARGET_LIST") == "true"
    if not path.is_file() and not listing:
        print(f"::error::{path} not found: deploy targets are the `[deploy]` tables of dockyard.toml", file=sys.stderr)
        return 1
    try:
        # `dockyard.toml` is optional: a repo without one has declared no targets, which a
        # listing (the release's question) answers with nothing rather than an error.
        targets = load_targets(path) if path.is_file() else []
        if listing:
            where_lines = [line for line in env.get("LIST_WHERE", "").splitlines() if line.strip()]
            text, log = _list(targets, parse_where([*where_lines, *args.where]))
        else:
            text, log = _resolve_one(targets, env)
    except (TargetsFileError, tomllib.TOMLDecodeError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    _emit(text, env.get("GITHUB_OUTPUT"))
    print(log, file=sys.stderr)
    return 0


if __name__ == "__main__":
    import os

    sys.exit(main(sys.argv[1:], os.environ))
