//! Rule `vendored-byte-exact` (AST part).
//!
//! In a file whose module doc claims vendoring or byte-exactness, any
//! Unicode `.to_lowercase()`/`.to_uppercase()` (as opposed to the ASCII
//! variants) can silently break byte-exactness on non-ASCII input.

use super::{line_of, Candidate, Rule};
use quote::ToTokens;
use syn::visit::Visit;
use syn::ExprMethodCall;

pub struct VendoredByteExact;

fn module_doc_claims_vendoring(ast: &syn::File) -> bool {
    ast.attrs.iter().any(|a| {
        a.path().is_ident("doc") && {
            let text = a.to_token_stream().to_string().to_ascii_lowercase();
            text.contains("vendored") || text.contains("byte-exact") || text.contains("serde")
        }
    })
}

fn unicode_casing_call(call: &ExprMethodCall) -> bool {
    let m = call.method.to_string();
    m == "to_lowercase" || m == "to_uppercase"
}

struct Visitor {
    out: Vec<Candidate>,
}

impl<'ast> Visit<'ast> for Visitor {
    fn visit_expr_method_call(&mut self, call: &'ast ExprMethodCall) {
        if unicode_casing_call(call) {
            self.out.push(Candidate {
                line: line_of(&call.method),
                violation: true,
            });
        }
        syn::visit::visit_expr_method_call(self, call);
    }
}

impl Rule for VendoredByteExact {
    fn id(&self) -> &'static str {
        "vendored-byte-exact"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        if !module_doc_claims_vendoring(ast) {
            return Vec::new();
        }
        let mut v = Visitor { out: Vec::new() };
        v.visit_file(ast);
        v.out
    }
}
