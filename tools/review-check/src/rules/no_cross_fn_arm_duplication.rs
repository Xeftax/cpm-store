//! Rule `no-cross-fn-arm-duplication`.
//!
//! If >= 2 match arms across different functions normalize to the same shape
//! (idents -> `I`, literals -> `L`), factor them into a shared helper and
//! feed it the differing pieces explicitly.

use super::{line_of, Candidate, Rule};
use quote::ToTokens;
use std::collections::HashMap;
use syn::visit::Visit;

// ==== Arm normalization ====

/// Normalize an expression: idents -> `I`, literals -> `L`, punctuation kept.
fn normalize(ts: proc_macro2::TokenStream) -> String {
    ts.into_iter()
        .map(|tt: proc_macro2::TokenTree| match tt {
            proc_macro2::TokenTree::Group(g) => format!("({})", normalize(g.stream())),
            proc_macro2::TokenTree::Ident(_) => "I".to_string(),
            proc_macro2::TokenTree::Literal(_) => "L".to_string(),
            proc_macro2::TokenTree::Punct(p) => p.as_char().to_string(),
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// (normalized shape, enclosing function id, line of the arm)
type Arm = (String, usize, usize);

// ==== Visitor ====

struct Visitor {
    out: Vec<Candidate>,
    arms: Vec<Arm>,
    fn_id: usize,
}

// ==== Visitor impl ====

impl Visitor {
    fn enter_fn(&mut self) -> usize {
        self.fn_id += 1;
        self.fn_id
    }
}

impl<'ast> Visit<'ast> for Visitor {
    // review: ignore duplicate-fn-bodies — syn visitor boilerplate, identical across rule files
    fn visit_item_fn(&mut self, f: &'ast syn::ItemFn) {
        let outer = self.fn_id;
        self.fn_id = self.enter_fn();
        syn::visit::visit_item_fn(self, f);
        self.fn_id = outer;
    }

    // review: ignore duplicate-fn-bodies — syn visitor boilerplate, identical across rule files
    fn visit_impl_item_fn(&mut self, m: &'ast syn::ImplItemFn) {
        let outer = self.fn_id;
        self.fn_id = self.enter_fn();
        syn::visit::visit_impl_item_fn(self, m);
        self.fn_id = outer;
    }

    fn visit_expr_match(&mut self, m: &'ast syn::ExprMatch) {
        for arm in &m.arms {
            let shape = normalize(arm.body.to_token_stream());
            if !shape.is_empty() {
                self.arms.push((shape, self.fn_id, line_of(&arm.body)));
            }
        }
        syn::visit::visit_expr_match(self, m);
    }
}

// ==== Rule impl ====

pub struct NoCrossFnArmDuplication;

impl Rule for NoCrossFnArmDuplication {
    fn id(&self) -> &'static str {
        "no-cross-fn-arm-duplication"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        let mut v = Visitor {
            out: Vec::new(),
            arms: Vec::new(),
            fn_id: 0,
        };
        v.visit_file(ast);
        // shape -> enclosing fn id -> lines in that fn
        let mut shapes: HashMap<String, HashMap<usize, Vec<usize>>> = HashMap::new();
        for (shape, fn_id, line) in &v.arms {
            shapes
                .entry(shape.clone())
                .or_default()
                .entry(*fn_id)
                .or_default()
                .push(*line);
        }
        // violation: same shape in >= 2 distinct functions
        for per_fn in shapes.values() {
            if per_fn.len() < 2 {
                continue;
            }
            for lines in per_fn.values() {
                for &line in lines {
                    v.out.push(Candidate {
                        line,
                        violation: true,
                    });
                }
            }
        }
        v.out
    }
}
