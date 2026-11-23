# docs/ — repository documentation

- `specs/` + `specs.md`: normative OMA specs (CPM-REST, REST-NMS, REST_NetAPI_Common).
  Any business rule cited in the code refers to a section of these specs.
- `adr/`: repository ADRs. `0001-review-known-patterns.md` = review memory (known-patterns).
- `TREE.md`: **auto-generated** by `tools/generate-filemap.py` — never edit it by hand.
  To change a description: fix the `//!` of the source file, then rerun the script.
- `conformance.md`: checklist of client SCRs (CPM-REST annex B).
- `architecture.md`, `roadmap.md`, `direction.md`: vision and trajectory.
