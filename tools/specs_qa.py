#!/usr/bin/env python3
"""Fidelity QA of the OMA spec markdown copies against the official PDFs.

For each spec: extract the PDF text with `pdftotext`, normalize (lowercase,
non-alphanumerics stripped -- tolerant to line breaks, hyphenation, case), then check:
1. the key normative strings (SCR identifiers, tokens, sample URLs, sections)
   are present in BOTH the PDF and the markdown;
2. a random sample of PDF sentences finds a match in the markdown
   (sentence coverage).

Usage:
    python3 tools/specs_qa.py --pdf-dir /tmp/cpm-research/pdf --md-dir docs/specs --out reports/specs-qa.json

Note: this QA detects OMISSIONS. It does not detect additions nor tables
flattened by a conversion -- for the normative annexes (SCR appendix B, MIME
C-H samples), extract directly from the PDF (pdftotext). The PDF remains the
normative authority.
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
    """Normalize a string for comparison: lowercase, non-alphanumerics stripped."""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def sentences(text: str) -> list[str]:
    """Split a text into sentences longer than MIN_SENTENCE_LEN characters."""
    text = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > MIN_SENTENCE_LEN]


def pdf_text(pdf: Path) -> str:
    """Extract the raw text of a PDF with pdftotext (PDF on stdin, text on stdout).

    The executable is resolved via the PATH by /usr/bin/env: argv contains only
    literals (a variable-resolved path would be a non-literal input for S603).
    """
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext not found on the PATH (poppler-utils required)")
    r = subprocess.run(
        ["/usr/bin/env", "pdftotext", "-", "-"],
        input=pdf.read_bytes(),
        capture_output=True,
        check=False,
        shell=False,
    )
    return r.stdout.decode("utf-8", errors="replace")


def run(pdf_dir: Path, md_dir: Path, out: Path | None, sample: int) -> int:
    """Compare each PDF/markdown spec; write the JSON report if `out`. Return 0."""
    random.seed(42)
    report: dict[str, dict[str, Any]] = {}
    for spec, keys in KEY_STRINGS.items():
        pdf = pdf_dir / (spec + ".pdf")
        md = md_dir / (spec + ".md")
        if not pdf.exists():
            report[spec] = {"error": f"missing PDF: {pdf}"}
            continue
        if not md.exists():
            report[spec] = {"error": f"missing markdown: {md}"}
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
            f"{spec}: keys {r['keys']}  sentence coverage {r['sentence_coverage']}"
            + (f"  PDF-only={key_pdf_only}" if key_pdf_only else "")
            + (f"  MD-only(additions!)={key_md_only}" if key_md_only else "")
        )

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"pdf_dir": str(pdf_dir), "md_dir": str(md_dir), "specs": report}, indent=2, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        print(f"report: {out}")
    return 0


def main() -> int:
    """CLI entry point: parse the arguments then run the QA."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--md-dir", default="docs/specs")
    ap.add_argument("--out", default=None, help="writes a JSON report here")
    ap.add_argument("--sample", type=int, default=300, help="number of sampled sentences per spec")
    args = ap.parse_args()
    return run(Path(args.pdf_dir), Path(args.md_dir), Path(args.out) if args.out else None, args.sample)


if __name__ == "__main__":
    sys.exit(main())
