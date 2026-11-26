//! Rule `match-arms-are-dispatch`.
//!
//! A `match` used as a dispatch table has short, uniform arms: a long arm
//! means the arm hides an algorithm that belongs in a named helper. Famous
//! case: `case.rs`, where the `CamelCase` arm of `apply_plain` swallowed the
//! whole rename algorithm while every other arm was a one-liner. Violation:
//! an arm body whose token count exceeds both 15 tokens and 3x the median.

use super::{line_of, Candidate, Rule};
use quote::ToTokens;
use syn::visit::Visit;

pub struct MatchArmsAreDispatch;

struct Visitor {
    out: Vec<Candidate>,
}

impl MatchArmsAreDispatch {
    fn arm_size(arm: &syn::Arm) -> usize {
        let ts: proc_macro2::TokenStream = arm.body.to_token_stream();
        fn leaves(ts: proc_macro2::TokenStream) -> usize {
            ts.into_iter()
                .map(|tt: proc_macro2::TokenTree| match tt {
                    proc_macro2::TokenTree::Group(g) => leaves(g.stream()),
                    _ => 1,
                })
                .sum()
        }
        leaves(ts)
    }
}

impl<'ast> Visit<'ast> for Visitor {
    fn visit_expr_match(&mut self, m: &'ast syn::ExprMatch) {
        let sizes: Vec<usize> = m.arms.iter().map(MatchArmsAreDispatch::arm_size).collect();
        let mut sorted = sizes.clone();
        sorted.sort_unstable();
        let median = sorted[sorted.len() / 2];
        let threshold = std::cmp::max(15, median.saturating_mul(3));
        for (arm, size) in m.arms.iter().zip(&sizes) {
            if *size > threshold {
                self.out.push(Candidate {
                    line: line_of(&arm.body),
                    violation: true,
                });
            }
        }
        syn::visit::visit_expr_match(self, m);
    }
}

impl Rule for MatchArmsAreDispatch {
    fn id(&self) -> &'static str {
        "match-arms-are-dispatch"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        let mut v = Visitor { out: Vec::new() };
        v.visit_file(ast);
        v.out
    }
}
