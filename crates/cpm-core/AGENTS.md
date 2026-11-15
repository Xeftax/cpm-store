# cpm-core — crate domaine pur

Core data model for OMA CPM (Converged Personal Messaging). **Aucun I/O, aucun unsafe, aucun
runtime async dans la lib** (tokio uniquement en dev-dependency pour les tests des ports).

- `src/model/` — types du domaine (voir `src/model/AGENTS.md`)
- `src/ports/` — traits async object-safe (`async-trait`) : contrats d'I/O, implémentés ailleurs
- `tests/` — golden tests (annexes de la spec) + mock des ports

Preuve depuis la racine du workspace : `cargo test -p cpm-core`, `cargo clippy -p cpm-core`.
