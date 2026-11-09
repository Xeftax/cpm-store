#!/usr/bin/env python3
"""QA de fidélité des copies markdown des specs OMA contre les PDF officiels.

Pour chaque spec : extrait le texte du PDF avec `pdftotext`, normalise (minuscules,
non-alphanum supprimé — tolère retours à la ligne, césures, casse), puis vérifie :
1. les chaînes normatives clés (identifiants SCR, tokens, URLs d'exemple, sections)
   sont présentes dans le PDF ET dans le markdown ;
2. un échantillon aléatoire de phrases du PDF retrouve un match dans le markdown
   (couverture de phrases).

Usage :
    python3 tools/specs_qa.py --pdf-dir /tmp/cpm-research/pdf --md-dir docs/specs --out reports/specs-qa.json

Note : cette QA détecte les OMISSIONS. Elle ne détecte pas les ajouts ni les tableaux
aplatis par une conversion — pour les annexes normatives (SCR annexe B, exemples
MIME C–H), extraire directement depuis le PDF (pdftotext). Le PDF reste l'autorité
normative.
"""

import argparse
import json
import os
import random
import re
import subprocess
import sys

KEY_STRINGS = {
    "OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C": [
        "restartToken", "lastModSeq", "nms/v1/base/tel:+12021308085/objects",
        "REST-NMS-AOBJECT-S-002-M", "Strict Synchronization", "First Time Sync",
        "Steady State Sync", "message/CPIM", "Bearer", "Appendix C",
        "5.2.1", "6.3.2", "conversation history folder", "group state object",
        "session info object", "file transfer history object",
    ],
    "OMA-TS-CPM_Message_Store-V2_2-20170926-C": [
        "RFC3501", "METADATA", "ANNOTATE", "List Folders", "MIME headers",
        "session history folder", "IMAP", "Appendix J",
    ],
    "OMA-TS-CPM_Conversation_Function-V2_2-20200907-C": [
        "Conversation-ID", "Contribution-ID", "message/cpim", "IMDN",
        "isComposing", "MSRP", "CPIM", "Disposition",
    ],
    "OMA-AD-CPM-V2_2-20170926-C": [
        "Converged IP Messaging", "Participating Function", "Controlling Function",
        "SIP/IP core", "Message Storage",
    ],
    "OMA-RD-CPM-V2_2-20170926-C": ["CPM User", "requirement", "Message Storage"],
    "OMA-TS-CPM_System_Description-V2_2-20170926-C": [
        "Message Storage", "SIP/IP core", "Converged",
    ],
    "OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C": [
        "nms/v1/myStore", "restartToken", "lastModSeq", "Strict Synchronization",
        "boxId", "NmsSubscription", "objects", "folders", "payloadParts",
        "notifications", "Bearer", "Appendix",
    ],
}


def norm_hard(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def sentences(text: str):
    text = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 40]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--md-dir", default="docs/specs")
    ap.add_argument("--out", default=None, help="écrit un rapport JSON ici")
    ap.add_argument("--sample", type=int, default=300, help="nb de phrases échantillonnées par spec")
    args = ap.parse_args()

    random.seed(42)
    report = {}
    for spec, keys in KEY_STRINGS.items():
        pdf = os.path.join(args.pdf_dir, spec + ".pdf")
        md = os.path.join(args.md_dir, spec + ".md")
        if not os.path.exists(pdf):
            report[spec] = {"error": f"PDF manquant: {pdf}"}
            continue
        if not os.path.exists(md):
            report[spec] = {"error": f"markdown manquant: {md}"}
            continue
        pdf_raw = subprocess.run(["pdftotext", pdf, "-"], capture_output=True, text=True).stdout
        md_raw = open(md, encoding="utf-8").read()
        pdf_hard, md_hard = norm_hard(pdf_raw), norm_hard(md_raw)

        key_ok = sum(1 for k in keys if norm_hard(k) in pdf_hard and norm_hard(k) in md_hard)
        key_pdf_only = [k for k in keys if norm_hard(k) in pdf_hard and norm_hard(k) not in md_hard]
        key_md_only = [k for k in keys if norm_hard(k) not in pdf_hard and norm_hard(k) in md_hard]

        sents = sentences(pdf_raw)
        sample = random.sample(sents, min(args.sample, len(sents)))
        hits = sum(1 for s in sample if norm_hard(s) in md_hard)
        report[spec] = {
            "keys": f"{key_ok}/{len(keys)}",
            "keys_pdf_only": key_pdf_only,
            "keys_md_only": key_md_only,
            "sentence_coverage": f"{hits}/{len(sample)} ({100*hits/len(sample):.0f}%)",
            "pdf_words": len(pdf_raw.split()),
            "md_bytes": len(md_raw.encode()),
        }
        r = report[spec]
        print(f"{spec}: clés {r['keys']}  couverture phrases {r['sentence_coverage']}"
              + (f"  PDF-only={key_pdf_only}" if key_pdf_only else "")
              + (f"  MD-only(ajouts!)={key_md_only}" if key_md_only else ""))

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"pdf_dir": args.pdf_dir, "md_dir": args.md_dir, "specs": report}, f, indent=2, ensure_ascii=False)
        print(f"rapport: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
