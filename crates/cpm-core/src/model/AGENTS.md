# model/ — OMA CPM / NMS domain model

Every `*.rs` file here has the same structure:

1. `//!` header (module role + REST-NMS / CPM-REST spec references with sections)
2. `use`, then thematic sections as `// ==== Title ====` banners
3. `#[cfg(test)] mod tests` at the bottom of the file

`mod.rs` documents the folder (`//!`) + declares `pub mod` + re-exports (`pub use`).

Domain rules (details in the owner skills `.vibe/skills/`, see the root AGENTS.md):
derive-first serde (`super::one_or_many` for XML-to-JSON string-or-array), structs as
owned types only, case-insensitive attribute names (REST-NMS §5.3.2.5), newtype/`Deref`,
factoring macros.

Role of each file: `docs/TREE.md` (auto-generated, do not edit by hand).
