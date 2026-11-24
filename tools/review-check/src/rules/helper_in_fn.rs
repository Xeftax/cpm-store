//! Rule `serde-helper-identity`: scope = all functions;
//! violation if a struct is declared INSIDE the block (Helper pattern, whatever its name).

use super::{fns, impl_methods, line_of, Candidate, Rule};
use syn::{Item, Stmt};

pub struct HelperInFn;

impl Rule for HelperInFn {
    fn id(&self) -> &'static str {
        "serde-helper-identity"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        // free functions AND impl methods (a serde Helper often lives inside
        // `impl Deserialize for X { fn deserialize(...) { struct Helper ... } }`)
        fns(ast)
            .map(|f: &syn::ItemFn| (line_of(&f.sig.ident), &*f.block))
            .chain(impl_methods(ast).map(|m: &syn::ImplItemFn| (line_of(&m.sig.ident), &m.block)))
            .map(|(line, block): (usize, &syn::Block)| Candidate {
                line,
                violation: block
                    .stmts
                    .iter()
                    .any(|s: &syn::Stmt| matches!(s, Stmt::Item(Item::Struct(_)))),
            })
            .collect()
    }
}
