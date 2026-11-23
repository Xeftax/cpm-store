//! Rule `closure-params-typed`: every closure parameter carries an explicit type
//! (`|a: &&Attribute|`), even when the compiler infers it. PR diffs are read without
//! IDE hover, and combinators like `Iterator::find` hand out double references
//! (`&&T`) that are easy to misread in a raw diff. `|_|` (wildcard) is the only
//! exception: there is no binding to type.

use super::{line_of, Candidate, Rule};
use syn::visit::Visit;
use syn::{ExprClosure, Pat};

pub struct ClosureParamsTyped;

struct Visitor {
    out: Vec<Candidate>,
}

impl<'ast> Visit<'ast> for Visitor {
    fn visit_expr_closure(&mut self, closure: &'ast ExprClosure) {
        for param in &closure.inputs {
            let violation = !matches!(param, Pat::Type(_) | Pat::Wild(_));
            self.out.push(Candidate {
                line: line_of(param),
                violation,
            });
        }
        syn::visit::visit_expr_closure(self, closure);
    }
}

impl Rule for ClosureParamsTyped {
    fn id(&self) -> &'static str {
        "closure-params-typed"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        let mut v = Visitor { out: Vec::new() };
        v.visit_file(ast);
        v.out
    }
}
