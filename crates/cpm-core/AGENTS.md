# cpm-core — pure domain crate

Core data model for OMA CPM (Converged Personal Messaging). **No I/O, no unsafe, no
async runtime in the lib** (tokio only as a dev-dependency for port tests).

- `src/model/` — domain types (see `src/model/AGENTS.md`)
- `src/ports/` — async object-safe traits (`async-trait`): I/O contracts, implemented elsewhere
- `tests/` — golden tests (spec annexes) + port mocks

Proof from the workspace root: `cargo test -p cpm-core`, `cargo clippy -p cpm-core`.
