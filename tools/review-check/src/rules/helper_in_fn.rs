//! Règle `serde-helper-identity` : périmètre = toutes les fonctions ;
//! violation si une struct est déclarée DANS le bloc (pattern Helper, quel que soit son nom).

use super::{fns, impl_methods, line_of, Candidate, Rule};
use syn::{Item, Stmt};

pub struct HelperInFn;

impl Rule for HelperInFn {
    fn id(&self) -> &'static str {
        "serde-helper-identity"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        // fonctions libres ET méthodes d'impl (un Helper serde vit souvent dans
        // `impl Deserialize for X { fn deserialize(...) { struct Helper ... } }`)
        fns(ast)
            .map(|f| (line_of(&f.sig.ident), &*f.block))
            .chain(impl_methods(ast).map(|m| (line_of(&m.sig.ident), &m.block)))
            .map(|(line, block)| Candidate {
                line,
                violation: block
                    .stmts
                    .iter()
                    .any(|s| matches!(s, Stmt::Item(Item::Struct(_)))),
            })
            .collect()
    }
}
