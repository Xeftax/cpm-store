# model/ — domain model OMA CPM / NMS

Chaque fichier `*.rs` ici a la même structure :

1. header `//!` (rôle du module + références spec REST-NMS / CPM-REST avec sections)
2. `use`, puis sections thématiques en bannière `// ==== Titre ====`
3. `#[cfg(test)] mod tests` en bas du fichier

`mod.rs` documente le dossier (`//!`) + déclare `pub mod` + ré-exporte (`pub use`).

Règles de domaine (détails dans les skills-owners `.vibe/skills/`, voir AGENTS.md racine) :
derive-first serde (`super::one_or_many` pour XML-to-JSON string-ou-array), structs en types
possédés uniquement, noms d'attributs case-insensitive (REST-NMS §5.3.2.5), newtype/`Deref`,
macros de factorisation.

Rôle de chaque fichier : `docs/TREE.md` (auto-généré, ne pas éditer à la main).
