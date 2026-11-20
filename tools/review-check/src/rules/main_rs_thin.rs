//! Règle `main-rs-thin` : périmètre = tous les items d'un fichier `main.rs` ;
//! violation si le fichier contient des définitions (struct/enum/trait/impl/mod inline)
//! — la logique métier va dans des modules, main.rs ne garde que le CLI.

use super::{line_of, Candidate, Rule};
use syn::Item;

pub struct MainRsThin;

impl Rule for MainRsThin {
    fn id(&self) -> &'static str {
        "main-rs-thin"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        ast.items
            .iter()
            .map(|item: &Item| Candidate {
                line: line_of(item),
                violation: matches!(
                    item,
                    Item::Struct(_) | Item::Enum(_) | Item::Trait(_) | Item::Impl(_) | Item::Mod(_) // mod inline avec body (les `mod x;` sont des Item::Mod sans content)
                ) && !matches!(item, Item::Mod(m) if m.content.is_none()),
            })
            .collect()
    }
}
