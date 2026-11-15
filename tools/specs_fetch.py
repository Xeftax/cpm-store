#!/usr/bin/env python3
"""Télécharge localement les PDF officiels des specs OMA utilisées par cpm-store.

Les specs OMA sont sous copyright OMA : usage interne/educatif autorisé,
REDISTRIBUTION INTERDITE sans permission écrite. Les PDF ne sont donc jamais
commités (voir .gitignore, région oma-specs-not-redistributable) : ce script les
télécharge dans docs/specs/pdf/ (gitignored) pour un usage local / CI.

Usage :
    python3 tools/specs_fetch.py                     # télécharge les 7 PDF
    python3 tools/specs_fetch.py --convert           # + conversion docling dans docs/specs/
    python3 tools/specs_fetch.py --convert --qa      # + QA fidélité (tools/specs_qa.py)

Le code de cpm-store reste publiable en open source (Apache-2.0) ; seules les
copies/dérivés des specs OMA sont exclues du dépôt public.
"""

import argparse
import http.client
import importlib
import os
import shutil
import ssl
import subprocess
import sys
import urllib.parse
from pathlib import Path

SPECS = [
    (
        "OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C",
        "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C.pdf",
    ),
    (
        "OMA-TS-CPM_Message_Store-V2_2-20170926-C",
        "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Message_Store-V2_2-20170926-C.pdf",
    ),
    (
        "OMA-TS-CPM_Conversation_Function-V2_2-20200907-C",
        "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Conversation_Function-V2_2-20200907-C.pdf",
    ),
    (
        "OMA-AD-CPM-V2_2-20170926-C",
        "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-AD-CPM-V2_2-20170926-C.pdf",
    ),
    (
        "OMA-RD-CPM-V2_2-20170926-C",
        "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-RD-CPM-V2_2-20170926-C.pdf",
    ),
    (
        "OMA-TS-CPM_System_Description-V2_2-20170926-C",
        "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_System_Description-V2_2-20170926-C.pdf",
    ),
    (
        "OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C",
        "https://www.openmobilealliance.org/release/REST_NETAPI_NMS/V1_0-20190528-C/OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C.pdf",
    ),
]

MIN_PDF_BYTES = 100_000
MAX_REDIRECTS = 5
HTTP_OK = 200
HTTP_REDIRECTS = (301, 302, 303, 307, 308)
# argv des appels subprocess : /usr/bin/env en argv[0] résout l'exécutable via le PATH, et
# seules des valeurs littérales suivent — un chemin résolu par variable serait un input
# non littéral (S603) ; les chemins dynamiques voyagent par l'environnement (kwargs).


def require_tool(tool: str) -> None:
    """Lève RuntimeError si `tool` n'est pas résolu dans le PATH (shutil.which)."""
    if shutil.which(tool) is None:
        raise RuntimeError(f"{tool} introuvable dans le PATH")


def https_get(url: str) -> bytes:
    """GET https sur `url` en pur Python (http.client), redirections https suivies."""
    parsed = urllib.parse.urlparse(url)
    for _ in range(MAX_REDIRECTS):
        if parsed.scheme != "https" or parsed.hostname is None:
            raise ValueError(f"URL https attendue: {url}")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        conn = http.client.HTTPSConnection(
            parsed.hostname, parsed.port or 443, context=ssl.create_default_context(), timeout=60
        )
        try:
            conn.request("GET", path, headers={"User-Agent": "cpm-store-tools"})
            resp = conn.getresponse()
            location = resp.getheader("Location")
            if resp.status in HTTP_REDIRECTS and location:
                resp.read()
                parsed = urllib.parse.urlparse(location)
                continue
            if resp.status != HTTP_OK:
                raise RuntimeError(f"HTTP {resp.status} en GET {url}")
            return resp.read()
        finally:
            conn.close()
    raise RuntimeError(f"trop de redirections (> {MAX_REDIRECTS}) pour {url}")


def convert_with_docling(pdf: Path, specs_dir: Path) -> subprocess.CompletedProcess[str]:
    """Convertit un PDF en markdown avec docling (via uvx), output dans specs_dir."""
    require_tool("uvx")
    return subprocess.run(
        [
            "/usr/bin/env",
            "uvx",
            "--from",
            "docling",
            "python",
            "-c",
            "import os, sys\n"
            "from docling.cli.main import app\n"
            "sys.argv = ['docling', 'convert', os.environ['CPM_DOCLING_SOURCE'], '--to', 'md', "
            "'--image-export-mode', 'referenced', '--output', os.environ['CPM_DOCLING_OUTPUT']]\n"
            "app()",
        ],
        env={**os.environ, "CPM_DOCLING_SOURCE": str(pdf), "CPM_DOCLING_OUTPUT": str(specs_dir)},
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )


def run_qa(pdf_dir: Path, specs_dir: Path, out: Path) -> int:
    """Lance la QA fidélité (tools/specs_qa.py) dans ce même interpréteur."""
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    qa_run = vars(importlib.import_module("specs_qa"))["run"]
    return int(qa_run(pdf_dir=pdf_dir, md_dir=specs_dir, out=out, sample=300))


def main() -> int:
    """Télécharge les PDF des specs OMA, optionnellement convertis (docling) puis QA."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", default="docs/specs/pdf")
    ap.add_argument("--specs-dir", default="docs/specs")
    ap.add_argument(
        "--convert", action="store_true", help="convertit les PDF en markdown avec docling dans --specs-dir"
    )
    ap.add_argument("--qa", action="store_true", help="lance tools/specs_qa.py après conversion")
    args = ap.parse_args()

    pdf_dir = Path(args.pdf_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for name, url in SPECS:
        dst = pdf_dir / (name + ".pdf")
        if dst.exists() and dst.stat().st_size > MIN_PDF_BYTES:
            print(f"skip (déjà là): {dst}")
            continue
        print(f"GET {url}")
        dst.write_bytes(https_get(url))
        print(f"  -> {dst} ({dst.stat().st_size:,} octets)")

    if args.convert:
        specs_dir = Path(args.specs_dir)
        for name, _ in SPECS:
            pdf = pdf_dir / (name + ".pdf")
            r = convert_with_docling(pdf, specs_dir)
            ok = "Finished converting" in r.stdout
            print(f"{'ok ' if ok else 'ERR'} {name}")
            if not ok:
                print(r.stdout[-500:], r.stderr[-500:])
                return 1
        # remonte les artifacts à côté des md et réécrit les chemins d'images absolus
        for f in specs_dir.glob("*.md"):
            text = f.read_text(encoding="utf-8")
            text = text.replace(str(specs_dir.resolve()) + "/", "")
            f.write_text(text, encoding="utf-8")

    if args.qa:
        return run_qa(pdf_dir, Path(args.specs_dir), Path("reports/specs-qa.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
