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
import subprocess
import sys
import urllib.request
from pathlib import Path

SPECS = [
    ("OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C",
     "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C.pdf"),
    ("OMA-TS-CPM_Message_Store-V2_2-20170926-C",
     "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Message_Store-V2_2-20170926-C.pdf"),
    ("OMA-TS-CPM_Conversation_Function-V2_2-20200907-C",
     "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_Conversation_Function-V2_2-20200907-C.pdf"),
    ("OMA-AD-CPM-V2_2-20170926-C",
     "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-AD-CPM-V2_2-20170926-C.pdf"),
    ("OMA-RD-CPM-V2_2-20170926-C",
     "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-RD-CPM-V2_2-20170926-C.pdf"),
    ("OMA-TS-CPM_System_Description-V2_2-20170926-C",
     "https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/OMA-TS-CPM_System_Description-V2_2-20170926-C.pdf"),
    ("OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C",
     "https://www.openmobilealliance.org/release/REST_NETAPI_NMS/V1_0-20190528-C/OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C.pdf"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", default="docs/specs/pdf")
    ap.add_argument("--specs-dir", default="docs/specs")
    ap.add_argument("--convert", action="store_true", help="convertit les PDF en markdown avec docling dans --specs-dir")
    ap.add_argument("--qa", action="store_true", help="lance tools/specs_qa.py après conversion")
    args = ap.parse_args()

    pdf_dir = Path(args.pdf_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for name, url in SPECS:
        dst = pdf_dir / (name + ".pdf")
        if dst.exists() and dst.stat().st_size > 100_000:
            print(f"skip (déjà là): {dst}")
            continue
        print(f"GET {url}")
        # openmobilealliance.org returns 403 to the default urllib User-Agent;
        # send a browser UA so the official PDFs can be fetched for local use.
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                                       "Chrome/126.0 Safari/537.36"})
        with urllib.request.urlopen(req) as resp, open(dst, "wb") as out:
            out.write(resp.read())
        print(f"  -> {dst} ({dst.stat().st_size:,} octets)")

    if args.convert:
        specs_dir = Path(args.specs_dir)
        for name, _ in SPECS:
            pdf = pdf_dir / (name + ".pdf")
            r = subprocess.run(["uvx", "--from", "docling", "docling", "convert", str(pdf),
                                "--to", "md", "--image-export-mode", "referenced",
                                "--output", str(specs_dir)],
                               capture_output=True, text=True)
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
        here = Path(__file__).resolve().parent
        r = subprocess.run([sys.executable, str(here / "specs_qa.py"),
                            "--pdf-dir", str(pdf_dir), "--md-dir", args.specs_dir,
                            "--out", "reports/specs-qa.json"])
        return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
