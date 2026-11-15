#!/usr/bin/env python3
"""Check des known-patterns (ADR 0001) sur les LIGNES AJOUTÉES d'un diff — WARNING ONLY.

Usage:
    python3 scripts/review/check-known-patterns.py [base] [ref]
Défaut: base=main, ref=HEAD (diff de la branche courante).
Ne matche que les lignes `+` du diff (pas les fichiers entiers) : un pattern déjà
présent avant la PR ne ressort pas. Lit .vibe/review/known-patterns.toml.

Règles (ADR 0001) : severity warning, exit 0 toujours (bloquant = compilateur/tests/clippy),
soupape `// review: ignore <rule-id>` sur la ligne, exclude_files verrouillé (accord
utilisateur requis — voir review-memory-owner).
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


def added_lines(base: str, ref: str) -> dict[str, list[tuple[int, str]]]:
    """Parse le diff et retourne {fichier: [(num_ligne_dans_le_nouveau_fichier, contenu)]}."""
    diff = subprocess.check_output(
        ["git", "diff", f"{base}...{ref}", "--", "*.rs"], cwd=ROOT, text=True
    )
    files: dict[str, list[tuple[int, str]]] = {}
    cur: str | None = None
    lineno = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
            files[cur] = []
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif cur is not None:
            if line.startswith("+") and not line.startswith("+++"):
                files[cur].append((lineno, line[1:]))
                lineno += 1
            elif not line.startswith("-"):
                lineno += 1
    return files


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "main"
    ref = sys.argv[2] if len(sys.argv) > 2 else "HEAD"

    patterns = tomllib.loads(TOML.read_text(encoding="utf-8"))["pattern"]
    files = added_lines(base, ref)
    hits = 0
    for p in patterns:
        rx = re.compile(p["regex"])
        excluded = set(p.get("exclude_files", []))
        for f, lines in sorted(files.items()):
            if not fnmatch.fnmatch(f, p["scope"]) or f in excluded:
                continue
            for lineno, content in lines:
                if rx.search(content) and f"review: ignore {p['id']}" not in content:
                    print(f"warning[{p['id']}] {f}:{lineno}: {content.strip()}")
                    print(f"    -> {p['message']}")
                    hits += 1

    n_files = len(files)
    print(
        f"\n{hits} known-pattern(s) en warning sur les lignes ajoutées du diff "
        f"{base}...{ref} ({n_files} fichiers .rs modifiés) — exit 0 (warning only, ADR 0001)"
    )


if __name__ == "__main__":
    main()
