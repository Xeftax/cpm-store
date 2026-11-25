//! Rule `total-vs-domain-contract` (AST part).
//!
//! A `pub` function taking `&str` must have a doc comment stating its
//! contract: totality (never panics for any input) and the input domain on
//! which stronger guarantees (parity with another implementation) hold.
//! Violation: `pub fn` (free or impl method) with a `&str` parameter and no
//! `#[doc]` attribute.

use super::{line_of, Candidate, Rule};
use quote::ToTokens;
use syn::visit::Visit;

pub struct TotalVsDomainContract;

/// True if the signature has a `&str` (or `&String`) parameter.
fn takes_str(sig: &syn::Signature) -> bool {
    sig.inputs.iter().any(|arg| match arg {
        syn::FnArg::Typed(p) => {
            let ty = p.ty.to_token_stream().to_string().replace(' ', "");
            ty.contains("&str") || ty.contains("&String")
        }
        _ => false,
    })
}

fn candidate_for(vis: &syn::Visibility, sig: &syn::Signature, attrs: &[syn::Attribute]) -> bool {
    let is_pub = matches!(vis, syn::Visibility::Public(_));
    let has_doc = attrs.iter().any(|a| a.path().is_ident("doc"));
    is_pub && takes_str(sig) && !has_doc
}

struct Visitor {
    out: Vec<Candidate>,
}

impl<'ast> Visit<'ast> for Visitor {
    fn visit_item_fn(&mut self, f: &'ast syn::ItemFn) {
        if candidate_for(&f.vis, &f.sig, &f.attrs) {
            self.out.push(Candidate {
                line: line_of(&f.sig.ident),
                violation: true,
            });
        }
        syn::visit::visit_item_fn(self, f);
    }

    fn visit_impl_item_fn(&mut self, m: &'ast syn::ImplItemFn) {
        if candidate_for(&m.vis, &m.sig, &m.attrs) {
            self.out.push(Candidate {
                line: line_of(&m.sig.ident),
                violation: true,
            });
        }
        syn::visit::visit_impl_item_fn(self, m);
    }
}

impl Rule for TotalVsDomainContract {
    fn id(&self) -> &'static str {
        "total-vs-domain-contract"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        let mut v = Visitor { out: Vec::new() };
        v.visit_file(ast);
        v.out
    }
}
