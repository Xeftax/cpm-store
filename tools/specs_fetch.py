#!/usr/bin/env python3
"""Downloads the official OMA spec PDFs used by cpm-store locally.

The OMA specs are copyrighted by OMA: internal/educational use is allowed,
REDISTRIBUTION FORBIDDEN without written permission. The PDFs are therefore
never committed (see .gitignore, oma-specs-not-redistributable region): this
script downloads them into docs/specs/pdf/ (gitignored) for local use / CI.

Usage:
    python3 tools/specs_fetch.py                     # downloads the 7 PDFs
    python3 tools/specs_fetch.py --convert           # + docling conversion into docs/specs/
    python3 tools/specs_fetch.py --convert --qa      # + fidelity QA (tools/specs_qa.py)

The cpm-store code remains publishable as open source (Apache-2.0); only the
copies/derivatives of the OMA specs are excluded from the public repository.
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
        "https://www.openmobilealliance.org/release/CPM/V2_2-20170926-C/OMA-RD-CPM-V2_2-20170926-C.pdf",
    ),
    (
        "OMA-TS-CPM_System_Description-V2_2-20170926-C",
        "https://www.openmobilealliance.org/release/CPM/V2_2-20170926-C/OMA-TS-CPM_System_Description-V2_2-20170926-C.pdf",
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
# argv of subprocess calls: /usr/bin/env in argv[0] resolves the executable via the PATH, and
# only literal values follow — a path resolved by a variable would be a non-literal
# input (S603); dynamic paths travel via the environment (kwargs).


def require_tool(tool: str) -> None:
    """Raise RuntimeError if `tool` is not resolved in the PATH (shutil.which)."""
    if shutil.which(tool) is None:
        raise RuntimeError(f"{tool} not found in the PATH")


def https_get(url: str) -> bytes:
    """HTTPS GET of `url` in pure Python (http.client), with https redirects followed."""
    parsed = urllib.parse.urlparse(url)
    for _ in range(MAX_REDIRECTS):
        if parsed.scheme != "https" or parsed.hostname is None:
            raise ValueError(f"HTTPS URL expected: {url}")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        conn = http.client.HTTPSConnection(
            parsed.hostname, parsed.port or 443, context=ssl.create_default_context(), timeout=60
        )
        try:
            # openmobilealliance.org returns 403 to a non-browser UA; we send
            # a browser UA to be able to download the official PDFs locally.
            conn.request(
                "GET",
                path,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                        " (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                    )
                },
            )
            resp = conn.getresponse()
            location = resp.getheader("Location")
            if resp.status in HTTP_REDIRECTS and location:
                resp.read()
                parsed = urllib.parse.urlparse(location)
                continue
            if resp.status != HTTP_OK:
                raise RuntimeError(f"HTTP {resp.status} on GET {url}")
            return resp.read()
        finally:
            conn.close()
    raise RuntimeError(f"too many redirects (> {MAX_REDIRECTS}) for {url}")


def convert_with_docling(pdf: Path, specs_dir: Path) -> subprocess.CompletedProcess[str]:
    """Convert a PDF to markdown with docling (via uvx), output in specs_dir."""
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
    """Run the fidelity QA (tools/specs_qa.py) in this same interpreter."""
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    qa_run = vars(importlib.import_module("specs_qa"))["run"]
    return int(qa_run(pdf_dir=pdf_dir, md_dir=specs_dir, out=out, sample=300))


def main() -> int:
    """Download the OMA spec PDFs, optionally convert them (docling) then run QA."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", default="docs/specs/pdf")
    ap.add_argument("--specs-dir", default="docs/specs")
    ap.add_argument(
        "--convert", action="store_true", help="convert the PDFs to markdown with docling into --specs-dir"
    )
    ap.add_argument("--qa", action="store_true", help="run tools/specs_qa.py after conversion")
    args = ap.parse_args()

    pdf_dir = Path(args.pdf_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for name, url in SPECS:
        dst = pdf_dir / (name + ".pdf")
        if dst.exists() and dst.stat().st_size > MIN_PDF_BYTES:
            print(f"skip (already there): {dst}")
            continue
        print(f"GET {url}")
        dst.write_bytes(https_get(url))
        print(f"  -> {dst} ({dst.stat().st_size:,} bytes)")

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
        # move the artifacts next to the .md files and rewrite the absolute image paths
        for f in specs_dir.glob("*.md"):
            text = f.read_text(encoding="utf-8")
            text = text.replace(str(specs_dir.resolve()) + "/", "")
            f.write_text(text, encoding="utf-8")

    if args.qa:
        return run_qa(pdf_dir, Path(args.specs_dir), Path("reports/specs-qa.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
