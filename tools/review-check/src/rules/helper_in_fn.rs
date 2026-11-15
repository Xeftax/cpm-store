//! Règle `serde-helper-identity` : périmètre = toutes les fonctions ;
//! violation si une struct est déclarée DANS le bloc (pattern Helper, quel que soit son nom).

use super::{fns, line_of, Candidate, Rule};
use syn::{Item, Stmt};

pub struct HelperInFn;

impl Rule for HelperInFn {
    fn id(&self) -> &'static str {
        "serde-helper-identity"
    }

    fn candidates(&self, ast: &syn::File) -> Vec<Candidate> {
        fns(ast)
            .map(|f| Candidate {
                line: line_of(&f.sig.ident),
                violation: f
                    .block
                    .stmts
                    .iter()
                    .any(|s| matches!(s, Stmt::Item(Item::Struct(_)))),
            })
            .collect()
    }
}
