//! Parsing of the `#[rest_json(...)]` attribute arguments into a [`Policy`].
//!
//! Recognized arguments (comma-separated):
//! - `rename_all = "camelCase"` (default) — one of serde's eight rule names,
//!   or `"none"` to emit no container-level `rename_all`;
//! - `acronyms("URL", ...)` — dictionary of words kept verbatim (full caps)
//!   when they appear as a `_`-separated word of a member ident;
//! - `rename(member = "wireName", ...)` — repeatable per-member wire-name
//!   override (wins over the computed rule output);
//! - `skip_none` (default) / `skip_none = false` — field rule: every
//!   `Option<...>` field without its own `skip_serializing_if` gets
//!   `skip_serializing_if = "Option::is_none"`;
//! - anything else (`default`, `deny_unknown_fields`, `tag = "..."`, ...) is
//!   forwarded verbatim into the emitted container-level `#[serde(...)]`.

use std::collections::BTreeMap;

use proc_macro2::TokenStream as TokenStream2;
use quote::quote;
use syn::meta::ParseNestedMeta;
use syn::parse::Parser;
use syn::{LitBool, LitStr, Meta, Token};

use crate::case::RenameRule;

// ==== Policy ====

#[derive(Debug)]
pub struct Policy {
    /// The rename rule to emit as container-level `rename_all`, if any.
    pub rename_all: Option<RenameRule>,
    /// Acronym dictionary (verbatim words), e.g. `["URL"]`.
    pub acronyms: Vec<String>,
    /// Per-member wire-name overrides: member ident (without `r#`) -> wire name.
    pub renames: BTreeMap<String, String>,
    /// Whether to add `skip_serializing_if = "Option::is_none"` to `Option` fields.
    pub skip_none: bool,
    /// Remaining arguments, forwarded verbatim into the container `#[serde(...)]`.
    pub forwarded: Vec<TokenStream2>,
}

// ==== Policy argument parsing ====

impl Policy {
    /// Parses the attribute arguments. `attr` is the raw token stream between
    /// the parentheses of `#[rest_json(...)]` (may be empty).
    pub fn parse(attr: proc_macro::TokenStream) -> syn::Result<Self> {
        let mut policy = Policy {
            rename_all: Some(RenameRule::CamelCase),
            acronyms: Vec::new(),
            renames: BTreeMap::new(),
            skip_none: true,
            forwarded: Vec::new(),
        };
        let parser = syn::punctuated::Punctuated::<Meta, Token![,]>::parse_terminated;
        let metas = parser.parse(attr)?;
        for meta in &metas {
            policy.apply_meta(meta)?;
        }
        if !policy.acronyms.is_empty() && policy.rename_all.is_none() {
            return Err(syn::Error::new(
                proc_macro2::Span::call_site(),
                "rest_json: `acronyms` requires a `rename_all` rule",
            ));
        }
        Ok(policy)
    }

    fn apply_meta(&mut self, meta: &Meta) -> syn::Result<()> {
        let path = meta.path();
        if path.is_ident("rename_all") {
            let lit: LitStr = parse_name_value(meta)?;
            self.rename_all = match lit.value().as_str() {
                "none" => None,
                rule => Some(RenameRule::parse(rule).ok_or_else(|| {
                    syn::Error::new_spanned(
                        &lit,
                        "rest_json: unknown rename_all rule (expected one of serde's eight \
                         rule names, or \"none\")",
                    )
                })?),
            };
        } else if path.is_ident("acronyms") {
            let Meta::List(list) = meta else {
                return Err(syn::Error::new_spanned(
                    meta,
                    "rest_json: expected acronyms(\"URL\", ...)",
                ));
            };
            let lits = list.parse_args_with(
                syn::punctuated::Punctuated::<LitStr, Token![,]>::parse_terminated,
            )?;
            for lit in lits {
                self.acronyms.push(lit.value());
            }
        } else if path.is_ident("rename") {
            let Meta::List(list) = meta else {
                return Err(syn::Error::new_spanned(
                    meta,
                    "rest_json: expected rename(member = \"wireName\", ...)",
                ));
            };
            list.parse_nested_meta(|nested: ParseNestedMeta| {
                let Some(ident) = nested.path.get_ident() else {
                    return Err(syn::Error::new_spanned(
                        &nested.path,
                        "rest_json: expected a member ident",
                    ));
                };
                let key = ident.to_string();
                let key = key.strip_prefix("r#").unwrap_or(&key).to_string();
                let lit: LitStr = nested.value()?.parse()?;
                self.renames.insert(key, lit.value());
                Ok(())
            })?;
        } else if path.is_ident("skip_none") {
            match meta {
                Meta::Path(_) => self.skip_none = true,
                Meta::NameValue(_) => {
                    let lit: LitBool = parse_name_value(meta)?;
                    self.skip_none = lit.value;
                }
                Meta::List(_) => {
                    return Err(syn::Error::new_spanned(
                        meta,
                        "rest_json: expected skip_none = false",
                    ));
                }
            }
        } else {
            // Forwarded verbatim into the emitted container-level #[serde(...)].
            self.forwarded.push(quote!(#meta));
        }
        Ok(())
    }
}

// ==== Helpers ====

fn parse_name_value<T: syn::parse::Parse>(meta: &Meta) -> syn::Result<T> {
    let Meta::NameValue(nv) = meta else {
        return Err(syn::Error::new_spanned(
            meta,
            "rest_json: expected `key = value`",
        ));
    };
    let value = &nv.value;
    syn::parse2(quote!(#value))
}
