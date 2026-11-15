//! Règle `manual-serde-impl` : périmètre = tous les impls de traits contenant
//! "Serialize" (quel que soit le lifetime) ; violation = à vérifier au cas par cas
//! (un derive + attributs champ suffit dans ~95% des cas).

use super::{impls, line_of, Candidate, Rule};

pub struct ManualSerdeImpl;

impl Rule for ManualSerdeImpl {
    fn id(&self) -> &'static str {
        "manual-serde-impl"
    }

    fn candidates(&self, ast: &syn::File) -> Vec<Candidate> {
        impls(ast)
            .filter(|imp| {
                imp.trait_
                    .as_ref()
                    .and_then(|(_, path, _)| path.segments.last())
                    .map(|seg| seg.ident.to_string().to_lowercase().contains("serialize"))
                    .unwrap_or(false)
            })
            .map(|imp| Candidate {
                line: line_of(imp),
                violation: true, // à valider : derive suffisant ?
            })
            .collect()
    }
}
