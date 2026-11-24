//! Rule `newtype-pub-with-delegation`: scope = all tuple structs;
//! violation if at least one field is `pub` (mix of transparent + encapsulated).

use super::{structs, Candidate, Rule};
use syn::{Fields, Visibility};

pub struct NewtypePub;

impl Rule for NewtypePub {
    fn id(&self) -> &'static str {
        "newtype-pub-with-delegation"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        structs(ast)
            .filter(|s: &&syn::ItemStruct| matches!(s.fields, Fields::Unnamed(_)))
            .map(|s: &syn::ItemStruct| Candidate {
                line: super::line_of(&s.ident),
                violation: s
                    .fields
                    .iter()
                    .any(|f: &syn::Field| matches!(f.vis, Visibility::Public(_))),
            })
            .collect()
    }
}
