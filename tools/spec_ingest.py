#!/usr/bin/env python3
"""Ingeste les PDF officiels des specs OMA CPM en markdown structuré via l'API Mistral OCR.

Pourquoi : les copies markdown actuelles (docs/specs/*.md) viennent d'une
conversion tierce (Xeftax/cpm-rag) avec pertes connues (hierarchie aplatie,
tableaux deformes, images perdues). Mistral OCR preserve la structure
(titres, sections, tableaux) et extrait les images.

Usage :
    MISTRAL_API_KEY=... python3 tools/spec_ingest.py \
        --pdf-dir /tmp/cpm-research/pdf --out-dir docs/specs/ocr [--only NOM]

Sortie : docs/specs/ocr/<SPEC>/full.md, docs/specs/ocr/<SPEC>/images/*,
         docs/specs/ocr/<SPEC>/meta.json (modele, nb pages, usage API)

Alternative open-source locale si pas de cle API : docling (IBM)
    uvx --from docling docling convert <pdf> --to md --image-export-mode placeholder
"""

import argparse
import base64
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Protocol


class _UploadedFile(Protocol):
    id: str


class _SignedUrl(Protocol):
    url: str


class _FilesClient(Protocol):
    def upload(self, file: dict[str, object]) -> _UploadedFile: ...

    def get_signed_url(self, file_id: str) -> _SignedUrl: ...

    def delete(self, file_id: str) -> object: ...


class _OcrPage(Protocol):
    markdown: str


class _OcrResponse(Protocol):
    pages: list[_OcrPage]


class _OcrClient(Protocol):
    def process(self, model: str, document: dict[str, str], include_image_base64: bool) -> _OcrResponse: ...


class _MistralClient(Protocol):
    files: _FilesClient
    ocr: _OcrClient


def ocr_pdf(client: _MistralClient, pdf_path: Path) -> _OcrResponse:
    """Envoie le PDF à l'API Mistral OCR, nettoie l'upload, retourne la réponse OCR."""
    with pdf_path.open("rb") as f:
        uploaded = client.files.upload(file={"file_name": pdf_path.name, "content": f})
    signed = client.files.get_signed_url(file_id=uploaded.id)
    resp = client.ocr.process(
        model="mistral-ocr-latest",
        document={"type": "file", "file_uri": signed.url},
        include_image_base64=True,
    )
    client.files.delete(file_id=uploaded.id)
    return resp


def main() -> int:
    """Point d'entrée : OCR de chaque PDF du --pdf-dir vers --out-dir."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", default=None, help="ne traiter qu'un PDF (substring du nom)")
    args = ap.parse_args()

    if not os.environ.get("MISTRAL_API_KEY"):
        print("ERREUR: MISTRAL_API_KEY non definie", file=sys.stderr)
        return 2

    # import lazy via importlib : mistralai est une dépendance optionnelle (hors pyproject),
    # le module doit rester importable sans elle (smoke tests).
    mistralai_mod = importlib.import_module("mistralai")
    client: _MistralClient = vars(mistralai_mod)["Mistral"](api_key=os.environ["MISTRAL_API_KEY"])
    pdf_dir, out_dir = Path(args.pdf_dir), Path(args.out_dir)
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if args.only:
        pdfs = [p for p in pdfs if args.only in p.name]
    if not pdfs:
        print("Aucun PDF trouve", file=sys.stderr)
        return 1

    for pdf in pdfs:
        print(f"OCR de {pdf.name} ...", flush=True)
        resp = ocr_pdf(client, pdf)
        dest = out_dir / pdf.stem
        (dest / "images").mkdir(parents=True, exist_ok=True)
        pages_md: list[str] = []
        n_images = 0
        for i, page in enumerate(resp.pages):
            pages_md.append(f"<!-- page {i + 1} -->\n\n{page.markdown}")
            for img in getattr(page, "images", None) or []:
                b64 = getattr(img, "image_base64", None)
                if not b64:
                    continue
                if "," in b64:  # data URL
                    b64 = b64.split(",", 1)[1]
                ext = "png"
                name = f"p{i + 1}_{n_images}.{ext}"
                (dest / "images" / name).write_bytes(base64.b64decode(b64))
                n_images += 1
        (dest / "full.md").write_text("\n\n".join(pages_md), encoding="utf-8")
        usage = getattr(resp, "usage", None)
        meta = {
            "source_pdf": str(pdf),
            "model": "mistral-ocr-latest",
            "pages": len(resp.pages),
            "images_extracted": n_images,
            "api_usage": usage.__dict__ if hasattr(usage, "__dict__") else usage,
        }
        (dest / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
        print(f"  -> {dest}/full.md ({len(resp.pages)} pages, {n_images} images)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
