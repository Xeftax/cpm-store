//! Rule `enum-declaration-order`.
//!
//! A `match` whose arms are all two-segment paths like `Enum::Variant` is a
//! dispatch table: reading it (and diffing it) is easier when the arms follow
//! the declaration order of the dispatched-on enum. Violation: arm order
//! differs from the declaration order of the enum named by the first path
//! segment of the arms. `Self::Variant` arms are skipped: `Self` cannot be
//! resolved to an enum name without type inference.

use super::{line_of, Candidate, Rule};
use std::collections::HashMap;
use syn::visit::Visit;

pub struct EnumDeclarationOrder;

/// enum name -> declaration order of its variants (for every enum in `ast`).
fn enum_variant_order(ast: &syn::File) -> HashMap<String, Vec<String>> {
    let mut map: HashMap<String, Vec<String>> = HashMap::new();
    for item in &ast.items {
        if let syn::Item::Enum(e) = item {
            map.insert(
                e.ident.to_string(),
                e.variants
                    .iter()
                    .map(|v: &syn::Variant| v.ident.to_string())
                    .collect(),
            );
        }
    }
    map
}

/// (first_path_segment, variant_name) of an arm body, if it is a
/// two-segment path like `Enum::Variant`.
fn arm_variant(body: &syn::Expr) -> Option<(String, String)> {
    if let syn::Expr::Path(p) = body {
        if p.path.segments.len() == 2 {
            let first = p.path.segments[0].ident.to_string();
            let second = p.path.segments[1].ident.to_string();
            return Some((first, second));
        }
    }
    None
}

struct Visitor {
    orders: HashMap<String, Vec<String>>,
    out: Vec<Candidate>,
}

impl<'ast> Visit<'ast> for Visitor {
    fn visit_expr_match(&mut self, m: &'ast syn::ExprMatch) {
        // All arm bodies must be two-segment paths with the same first segment
        // naming an enum declared in this file.
        let mut first: Option<String> = None;
        let mut variants: Vec<String> = Vec::new();
        for arm in &m.arms {
            let Some((head, variant)) = arm_variant(&arm.body) else {
                first = None;
                break;
            };
            if !self.orders.contains_key(&head) {
                first = None;
                break;
            }
            if let Some(h) = &first {
                if h != &head {
                    first = None;
                    break;
                }
            } else {
                first = Some(head.clone());
            }
            variants.push(variant);
        }
        if let Some(enum_name) = first {
            let order = &self.orders[&enum_name];
            let positions: Option<Vec<usize>> = variants
                .iter()
                .map(|v: &String| order.iter().position(|d: &String| d == v))
                .collect();
            if let Some(positions) = positions {
                let mut sorted = positions.clone();
                sorted.sort_unstable();
                if positions != sorted {
                    self.out.push(Candidate {
                        line: line_of(&m.expr),
                        violation: true,
                    });
                }
            }
        }
        syn::visit::visit_expr_match(self, m);
    }
}

impl Rule for EnumDeclarationOrder {
    fn id(&self) -> &'static str {
        "enum-declaration-order"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        let mut v = Visitor {
            orders: enum_variant_order(ast),
            out: Vec::new(),
        };
        v.visit_file(ast);
        v.out
    }
}
