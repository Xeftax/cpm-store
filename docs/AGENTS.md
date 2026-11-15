# docs/ — documentation du repo

- `specs/` + `specs.md` : specs OMA normatives (CPM-REST, REST-NMS, REST_NetAPI_Common).
  Toute règle métier citée dans le code renvoie à une section de ces specs.
- `adr/` : ADR du repo. `0001-review-known-patterns.md` = mémoire de review (known-patterns).
- `TREE.md` : **auto-généré** par `tools/generate-filemap.py` — ne jamais l'éditer à la main.
  Pour changer une description : corriger le `//!` du fichier source, puis relancer le script.
- `conformance.md` : checklist des SCR client (annexe B CPM-REST).
- `architecture.md`, `roadmap.md`, `direction.md` : vision et trajectoire.
