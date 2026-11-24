//! Rule `main-rs-thin`: scope = all items of a `main.rs` file;
//! violation if the file contains definitions (struct/enum/trait/impl/inline mod)
//! — business logic goes into modules, main.rs only keeps the CLI.

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
                    Item::Struct(_) | Item::Enum(_) | Item::Trait(_) | Item::Impl(_) | Item::Mod(_) // inline mod with body (the `mod x;` are Item::Mod without content)
                ) && !matches!(item, Item::Mod(m) if m.content.is_none()),
            })
            .collect()
    }
}
