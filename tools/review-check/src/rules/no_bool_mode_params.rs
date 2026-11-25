//! Rule `no-bool-mode-params`.
//!
//! A `bool` parameter is a call-site trap: `f(x, true)` reads as nothing. The
//! fix is a small named enum (`IdentKind::Variant` / `IdentKind::Field`
//! replaced `is_variant: bool` in `case.rs`). Violation: a free function or an
//! impl method with a parameter of type `bool`. `#[cfg(test)]` modules are
//! skipped.
//!
//! Escape hatch: `// review: ignore no-bool-mode-params`.

use super::{line_of, Candidate, Rule};
use quote::ToTokens;
use syn::visit::Visit;
use syn::{FnArg, ItemFn, ItemMod};

pub struct NoBoolModeParams;

fn has_bool_param(inputs: &syn::punctuated::Punctuated<FnArg, syn::token::Comma>) -> bool {
    inputs.iter().any(|arg| match arg {
        FnArg::Typed(p) => p.ty.to_token_stream().to_string() == "bool",
        FnArg::Receiver(_) => false,
    })
}

fn is_cfg_test(attrs: &[syn::Attribute]) -> bool {
    for a in attrs {
        if a.path().is_ident("cfg") {
            let text = a.to_token_stream().to_string();
            if text.contains("test") {
                return true;
            }
        }
    }
    false
}

struct Visitor {
    out: Vec<Candidate>,
    test_depth: usize,
}

impl<'ast> Visit<'ast> for Visitor {
    fn visit_item_mod(&mut self, m: &'ast ItemMod) {
        if is_cfg_test(&m.attrs) {
            self.test_depth += 1;
            if let Some((_, items)) = &m.content {
                for item in items {
                    syn::visit::visit_item(self, item);
                }
            }
            self.test_depth -= 1;
        } else {
            syn::visit::visit_item_mod(self, m);
        }
    }

    fn visit_item_fn(&mut self, f: &'ast ItemFn) {
        if self.test_depth == 0 && has_bool_param(&f.sig.inputs) {
            self.out.push(Candidate {
                line: line_of(&f.sig.ident),
                violation: true,
            });
        }
        syn::visit::visit_item_fn(self, f);
    }

    fn visit_item_impl(&mut self, imp: &'ast syn::ItemImpl) {
        if self.test_depth == 0 {
            for item in &imp.items {
                if let syn::ImplItem::Fn(m) = item {
                    if has_bool_param(&m.sig.inputs) {
                        self.out.push(Candidate {
                            line: line_of(&m.sig.ident),
                            violation: true,
                        });
                    }
                }
            }
        }
        syn::visit::visit_item_impl(self, imp);
    }
}

impl Rule for NoBoolModeParams {
    fn id(&self) -> &'static str {
        "no-bool-mode-params"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        let mut v = Visitor {
            out: Vec::new(),
            test_depth: 0,
        };
        v.visit_file(ast);
        v.out
    }
}
