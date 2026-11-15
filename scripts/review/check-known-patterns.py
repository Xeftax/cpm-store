#!/usr/bin/env python3
"""Check des known-patterns (ADR 0001) sur un diff — WARNING ONLY, jamais bloquant.

Usage:
    python3 scripts/review/check-known-patterns.py [base] [ref]
Défaut: base=main, ref=HEAD (diff de la branche courante).
Lit .vibe/review/known-patterns.toml ; si ref est fourni, lit les fichiers via
`git show ref:path` (permet de checker une PR distante, ex. origin/phase1/cpm-core).

Règles (ADR 0001) : check sur le diff uniquement, severity warning, soupape
`// review: ignore <rule-id>`, exit code toujours 0 (bloquant = compilateur/tests/clippy).
"""

import fnmatch
import pathlib
import re
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(
    subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
)
TOML = ROOT / ".vibe" / "review" / "known-patterns.toml"


def read_lines(ref: str | None, path: str) -> list[str]:
    if ref is None:
        return (ROOT / path).read_text(encoding="utf-8", errors="replace").splitlines()
    out = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, text=True
    )
    return out.stdout.splitlines() if out.returncode == 0 else []


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "main"
    ref = sys.argv[2] if len(sys.argv) > 2 else "HEAD"

    files = subprocess.check_output(
        ["git", "diff", "--name-only", f"{base}...{ref}"], cwd=ROOT, text=True
    ).splitlines()
    rs_files = [f for f in files if f.endswith(".rs")]

    patterns = tomllib.loads(TOML.read_text(encoding="utf-8"))["pattern"]
    hits = 0
    for p in patterns:
        rx = re.compile(p["regex"])
        excluded = set(p.get("exclude_files", []))
        for f in rs_files:
            if not fnmatch.fnmatch(f, p["scope"]) or f in excluded:
                continue
            for i, line in enumerate(read_lines(None if ref == "HEAD" else ref, f), 1):
                if rx.search(line) and f"review: ignore {p['id']}" not in line:
                    print(f"warning[{p['id']}] {f}:{i}: {line.strip()}")
                    print(f"    -> {p['message']}")
                    hits += 1

    print(
        f"\n{hits} known-pattern(s) en warning sur le diff {base}...{ref} "
        f"({len(rs_files)} fichiers .rs) — exit 0 (warning only, ADR 0001)"
    )


if __name__ == "__main__":
    main()
