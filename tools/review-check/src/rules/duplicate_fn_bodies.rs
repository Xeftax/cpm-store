//! Rule `duplicate-fn-bodies`: two functions (or methods) with the same body
//! up to an identifier/literal are duplication -> factor out (macro_rules!,
//! trait, or shared helper). Textbook case: message_context()/direction() in
//! attribute.rs (PR #3) = `first_value(NAME).map(T::parse)`.
//!
//! Normalization: each Ident token -> "I", Literal -> "S" (via proc-macro2),
//! then hash of the normalized body. Threshold: body >= 12 tokens to avoid noise
//! on trivial delegations (already covered by manual-delegation-methods).

use super::{fns, impl_methods, line_of, Candidate, Rule};
use proc_macro2::{Delimiter, TokenStream, TokenTree};
use std::collections::HashMap;

const MIN_TOKENS: usize = 8; // below: trivial delegations (self.0.len() ~ 6 tokens), already covered by manual-delegation-methods

pub struct DuplicateFnBodies;

impl Rule for DuplicateFnBodies {
    fn id(&self) -> &'static str {
        "duplicate-fn-bodies"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        let mut bodies: Vec<(usize, String)> = Vec::new();
        let free = fns(ast).map(|f: &syn::ItemFn| (line_of(&f.sig.ident), &*f.block));
        let methods =
            impl_methods(ast).map(|m: &syn::ImplItemFn| (line_of(&m.sig.ident), &m.block));
        for (line, block) in free.chain(methods) {
            let norm = normalize(quote::ToTokens::to_token_stream(block));
            if norm.split_whitespace().count() >= MIN_TOKENS {
                bodies.push((line, norm));
            }
        }
        let mut groups: HashMap<String, Vec<usize>> = HashMap::new();
        for (line, norm) in bodies {
            groups.entry(norm).or_default().push(line);
        }
        let mut out = Vec::new();
        for lines in groups.values() {
            let violation = lines.len() >= 2;
            for &line in lines {
                out.push(Candidate { line, violation });
            }
        }
        out
    }
}

/// Idents -> "I", literals -> "S", explicit delimiters.
fn normalize(ts: TokenStream) -> String {
    ts.into_iter()
        .map(|tt: TokenTree| match tt {
            TokenTree::Ident(_) => "I".to_string(),
            TokenTree::Literal(_) => "S".to_string(),
            TokenTree::Punct(p) => p.as_char().to_string(),
            TokenTree::Group(g) => {
                let (o, c) = match g.delimiter() {
                    Delimiter::Parenthesis => ("(", ")"),
                    Delimiter::Brace => ("{", "}"),
                    Delimiter::Bracket => ("[", "]"),
                    Delimiter::None => ("", ""),
                };
                format!("{o}{}{c}", normalize(g.stream()))
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}
