//! Règle `duplicate-fn-bodies` : deux fonctions (ou méthodes) avec le même corps
//! à un identifiant/literal près sont de la duplication -> factoriser (macro_rules!,
//! trait, ou helper partagé). Cas d'école : message_context()/direction() dans
//! attribute.rs (PR #3) = `first_value(NOM).map(T::parse)`.
//!
//! Normalisation : chaque token Ident -> "I", Literal -> "S" (via proc-macro2),
//! puis hash du corps normalisé. Seuil : corps >= 12 tokens pour éviter le bruit
//! sur les délégations triviales (déjà couvertes par manual-delegation-methods).

use super::{fns, impl_methods, line_of, Candidate, Rule};
use proc_macro2::{Delimiter, TokenStream, TokenTree};
use std::collections::HashMap;

const MIN_TOKENS: usize = 8; // en dessous: délégations triviales (self.0.len() ~ 6 tokens), déjà couvertes par manual-delegation-methods

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

/// Identifiants -> "I", literals -> "S", délimiteurs explicites.
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
