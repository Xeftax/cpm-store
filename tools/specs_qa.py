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
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

KEY_STRINGS = {
    "OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C": [
        "restartToken",
        "lastModSeq",
        "nms/v1/base/tel:+12021308085/objects",
        "REST-NMS-AOBJECT-S-002-M",
        "Strict Synchronization",
        "First Time Sync",
        "Steady State Sync",
        "message/CPIM",
        "Bearer",
        "Appendix C",
        "5.2.1",
        "6.3.2",
        "conversation history folder",
        "group state object",
        "session info object",
        "file transfer history object",
    ],
    "OMA-TS-CPM_Message_Store-V2_2-20170926-C": [
        "RFC3501",
        "METADATA",
        "ANNOTATE",
        "List Folders",
        "MIME headers",
        "session history folder",
        "IMAP",
        "Appendix J",
    ],
    "OMA-TS-CPM_Conversation_Function-V2_2-20200907-C": [
        "Conversation-ID",
        "Contribution-ID",
        "message/cpim",
        "IMDN",
        "isComposing",
        "MSRP",
        "CPIM",
        "Disposition",
    ],
    "OMA-AD-CPM-V2_2-20170926-C": [
        "Converged IP Messaging",
        "Participating Function",
        "Controlling Function",
        "SIP/IP core",
        "Message Storage",
    ],
    "OMA-RD-CPM-V2_2-20170926-C": ["CPM User", "requirement", "Message Storage"],
    "OMA-TS-CPM_System_Description-V2_2-20170926-C": [
        "Message Storage",
        "SIP/IP core",
        "Converged",
    ],
    "OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C": [
        "nms/v1/myStore",
        "restartToken",
        "lastModSeq",
        "Strict Synchronization",
        "boxId",
        "NmsSubscription",
        "objects",
        "folders",
        "payloadParts",
        "notifications",
        "Bearer",
        "Appendix",
    ],
}

MIN_SENTENCE_LEN = 40


def norm_hard(s: str) -> str:
    """Normalise une chaîne pour comparaison : minuscules, non-alphanum supprimé."""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def sentences(text: str) -> list[str]:
    """Découpe un texte en phrases de plus de MIN_SENTENCE_LEN caractères."""
    text = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > MIN_SENTENCE_LEN]


def pdf_text(pdf: Path) -> str:
    """Extrait le texte brut d'un PDF avec pdftotext (PDF en stdin, texte en stdout).

    L'exécutable est résolu via le PATH par /usr/bin/env : argv ne contient que des
    littéraux (un chemin résolu en variable serait un input non littéral pour S603).
    """
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext introuvable dans le PATH (poppler-utils requis)")
    r = subprocess.run(
        ["/usr/bin/env", "pdftotext", "-", "-"],
        input=pdf.read_bytes(),
        capture_output=True,
        check=False,
        shell=False,
    )
    return r.stdout.decode("utf-8", errors="replace")


def run(pdf_dir: Path, md_dir: Path, out: Path | None, sample: int) -> int:
    """Compare chaque spec PDF/markdown ; écrit le rapport JSON si `out`. Retourne 0."""
    random.seed(42)
    report: dict[str, dict[str, Any]] = {}
    for spec, keys in KEY_STRINGS.items():
        pdf = pdf_dir / (spec + ".pdf")
        md = md_dir / (spec + ".md")
        if not pdf.exists():
            report[spec] = {"error": f"PDF manquant: {pdf}"}
            continue
        if not md.exists():
            report[spec] = {"error": f"markdown manquant: {md}"}
            continue
        try:
            pdf_raw = pdf_text(pdf)
        except RuntimeError as err:
            report[spec] = {"error": str(err)}
            continue
        md_raw = md.read_text(encoding="utf-8")
        pdf_hard, md_hard = norm_hard(pdf_raw), norm_hard(md_raw)

        key_ok = sum(1 for k in keys if norm_hard(k) in pdf_hard and norm_hard(k) in md_hard)
        key_pdf_only = [k for k in keys if norm_hard(k) in pdf_hard and norm_hard(k) not in md_hard]
        key_md_only = [k for k in keys if norm_hard(k) not in pdf_hard and norm_hard(k) in md_hard]

        sents = sentences(pdf_raw)
        sampled = random.sample(sents, min(sample, len(sents)))
        hits = sum(1 for s in sampled if norm_hard(s) in md_hard)
        report[spec] = {
            "keys": f"{key_ok}/{len(keys)}",
            "keys_pdf_only": key_pdf_only,
            "keys_md_only": key_md_only,
            "sentence_coverage": f"{hits}/{len(sampled)} ({100 * hits / len(sampled):.0f}%)",
            "pdf_words": len(pdf_raw.split()),
            "md_bytes": len(md_raw.encode()),
        }
        r = report[spec]
        print(
            f"{spec}: clés {r['keys']}  couverture phrases {r['sentence_coverage']}"
            + (f"  PDF-only={key_pdf_only}" if key_pdf_only else "")
            + (f"  MD-only(ajouts!)={key_md_only}" if key_md_only else "")
        )

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"pdf_dir": str(pdf_dir), "md_dir": str(md_dir), "specs": report}, indent=2, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        print(f"rapport: {out}")
    return 0


def main() -> int:
    """Point d'entrée CLI : parse les arguments puis lance la QA."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--md-dir", default="docs/specs")
    ap.add_argument("--out", default=None, help="écrit un rapport JSON ici")
    ap.add_argument("--sample", type=int, default=300, help="nb de phrases échantillonnées par spec")
    args = ap.parse_args()
    return run(Path(args.pdf_dir), Path(args.md_dir), Path(args.out) if args.out else None, args.sample)


if __name__ == "__main__":
    sys.exit(main())
