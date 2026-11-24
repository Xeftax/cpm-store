# Embedded OMA specs

This directory contains the **markdown** copies of the 7 OMA specifications used
by this project (6 CPM V2_2 specs + `OMA-TS-REST_NetAPI_NMS`, base of the REST
binding). The official PDFs published on https://www.openmobilealliance.org/release/
remain the **normative reference**; these copies are a reading context (human and
LLM). Each `<spec>.md` comes with its `<spec>_artifacts/` directory (extracted
images, referenced with relative paths).

## Provenance

- **Official PDFs**: Open Mobile Alliance —
  - CPM V2_2: https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/
  - REST_NetAPI_NMS: https://www.openmobilealliance.org/release/REST_NETAPI_NMS/V1_0-20190528-C/
    (© Open Mobile Alliance Ltd., published under the terms stated in each document).
- **PDF → markdown conversion: done in this repo**, on 2026-11-08, with
  [docling](https://github.com/docling-project/docling)
  (`docling convert <pdf> --to md --image-export-mode referenced`), heading
  hierarchy and tables better preserved than the third-party conversion.
  The older markdown copies taken as-is from the third-party repository
  [Xeftax/cpm-rag](https://github.com/Xeftax/cpm-rag) have been **replaced** on
  2026-11-08 (they remain in the git history and in that third-party repository).
- The PDFs themselves are **not** committed (see the "Publication" section below).

## Publication (public open-source repo)

The **code** of cpm-store is freely publishable (Apache-2.0, original work).
The OMA documents, on the other hand, are under **OMA copyright**: the terms
("Used with the permission of the Open Mobile Alliance", Use Agreement
omaspecworks.org) allow **internal/educational use only** — not redistribution.
The following are therefore **gitignored and never committed** (`oma-specs-not-redistributable`
region of `.gitignore`):

- `docs/specs/pdf/` (the downloaded PDFs),
- `docs/specs/OMA-*.md` and `docs/specs/*_artifacts/` (markdown conversions + images),
- the **golden fixtures extracted from the spec annexes** (they are part of the
  OMA document) — the tests must generate them at test time from the local PDFs,
  not embed them.

To work locally or in CI: `python3 tools/specs_fetch.py --convert --qa`
downloads the 7 official PDFs from openmobilealliance.org, converts them
(docling) and runs the QA. Quoting a section number or short excerpts in
our own docs remains OK; copying the content of the specs is not.

- A conversion via **Mistral OCR** remains possible with `tools/spec_ingest.py`
  when `MISTRAL_API_KEY` is exported in the shell.

## Quality check (2026-11-08, rerun after restructuring)

Tool: `tools/specs_qa.py` (report: `reports/specs-qa.json`).
Method: PDF text via `pdftotext`, compared with the markdown after
normalization (lowercase, non-alphanumeric removed — tolerant of line breaks,
hyphenation, casing).

Results on the 7 canonical markdown files:

- **Key normative strings** (SCR identifiers, `restartToken`/`lastModSeq` tokens,
  sample `/nms/v1/...` URLs, `5.2.1`/`6.3.2` sections, CPM object types, etc.):
  **54/54 present both in the PDF and in the markdown** (12–16 keys per spec).
- **Random sample of 300 sentences per spec**: 67–79% exact match.
  The unmatched sentences are PDF layout artifacts (headers, footers
  "Used with the permission of the Open Mobile Alliance", page numbers,
  sentences split across page breaks).

Known limitations of this QA: it detects **omissions**, not additions nor
tables flattened by a conversion. **For the normative annexes** (SCR annex B,
JSON/MIME examples annexes C–H, which will serve as golden fixtures): **extract
directly from the PDF with `pdftotext`**, using the markdown as a reading aid.
When in doubt, the official PDF is authoritative.
