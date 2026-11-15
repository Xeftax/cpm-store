//! Règle `newtype-pub-with-delegation` : périmètre = tous les tuple structs ;
//! violation si au moins un champ est `pub` (mélange transparent + encapsulé).

use super::{structs, Candidate, Rule};
use syn::{Fields, Visibility};

pub struct NewtypePub;

impl Rule for NewtypePub {
    fn id(&self) -> &'static str {
        "newtype-pub-with-delegation"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        structs(ast)
            .filter(|s| matches!(s.fields, Fields::Unnamed(_)))
            .map(|s| Candidate {
                line: super::line_of(&s.ident),
                violation: s
                    .fields
                    .iter()
                    .any(|f| matches!(f.vis, Visibility::Public(_))),
            })
            .collect()
    }
}
