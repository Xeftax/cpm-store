//! Rule `manual-serde-impl`: scope = all trait impls containing
//! "Serialize" (whatever the lifetime); violation = to be validated case by case
//! (a derive + field attributes suffices in ~95% of cases).

use super::{impls, line_of, Candidate, Rule};

pub struct ManualSerdeImpl;

impl Rule for ManualSerdeImpl {
    fn id(&self) -> &'static str {
        "manual-serde-impl"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        impls(ast)
            .filter(|imp: &&syn::ItemImpl| {
                imp.trait_
                    .as_ref()
                    .and_then(
                        |t: &(Option<syn::token::Not>, syn::Path, syn::token::For)| {
                            t.1.segments.last()
                        },
                    )
                    .map(|seg: &syn::PathSegment| {
                        seg.ident.to_string().to_lowercase().contains("serialize")
                    })
                    .unwrap_or(false)
            })
            .map(|imp: &syn::ItemImpl| Candidate {
                line: line_of(imp),
                violation: true, // to validate: is a derive enough?
            })
            .collect()
    }
}
