//! `match-not-if-else-on-enum`: an `if`/`else` whose condition is an equality
//! test against an enum variant (`if x == SomeEnum::Variant { .. } else { .. }`)
//! is a disguised switch; use `match` instead. Only two-segment paths
//! (`SomeEnum::Variant`) are considered, to skip comparisons against locals.
//! Early-return guards without an `else` branch are fine and not flagged.

use super::{Candidate, Rule};
use syn::spanned::Spanned;
use syn::visit::Visit;
use syn::BinOp;
use syn::Expr;

pub struct MatchNotIfElseOnEnum;

fn enum_eq_condition(cond: &Expr) -> bool {
    if let Expr::Binary(b) = cond {
        if matches!(b.op, BinOp::Eq(_)) {
            for e in [&*b.left, &*b.right] {
                if let Expr::Path(p) = e {
                    if p.path.segments.len() == 2 {
                        let secs: Vec<_> = p.path.segments.iter().collect();
                        let first = secs[0].ident.to_string();
                        let second = secs[1].ident.to_string();
                        if first.chars().next().is_some_and(|c| c.is_uppercase())
                            && second.chars().next().is_some_and(|c| c.is_uppercase())
                        {
                            return true;
                        }
                    }
                }
            }
        }
    }
    false
}

impl<'ast> Visit<'ast> for Visitor {
    fn visit_expr_if(&mut self, node: &'ast syn::ExprIf) {
        // Only a real if/else (disguised switch), not an early-return guard.
        if node.else_branch.is_some() && enum_eq_condition(&node.cond) {
            self.out.push(Candidate {
                line: node.span().start().line,
                violation: true,
            });
        }
        syn::visit::visit_expr_if(self, node);
    }
}

struct Visitor {
    out: Vec<Candidate>,
}

impl Rule for MatchNotIfElseOnEnum {
    fn id(&self) -> &'static str {
        "match-not-if-else-on-enum"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        let mut v = Visitor { out: Vec::new() };
        v.visit_file(ast);
        v.out
    }
}
