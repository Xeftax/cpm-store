//! `rest-json` — container-level serde policy attribute `#[rest_json]` for the
//! CPM REST/JSON wire format (`REST_NetAPI_Common` XML-to-JSON rules: camelCase
//! element names, acronyms kept in full caps like `resourceURL`).
//!
//! The macro does not re-implement serde: it **lowers to plain `#[serde(...)]`
//! attributes** (dtolnay's recommended pattern for custom rename rules,
//! serde-rs/serde#2153) and lets `#[derive(Serialize, Deserialize)]` do the
//! real work. Place it **above** `#[derive(...)]` — attribute macros expand
//! outside-in, and a misplaced `#[rest_json]` is a compile error, not a silent
//! no-op.
//!
//! ```ignore
//! #[rest_json]                                        // rename_all = "camelCase", skip_none
//! #[rest_json(default)]                               // other args -> container #[serde(default)]
//! #[rest_json(acronyms("URL"))]                       // resource_url -> resourceURL
//! #[rest_json(rename(disposition_type = "type"))]     // per-member wire override
//! #[rest_json(rename_all = "snake_case", skip_none = false)]
//! #[derive(Debug, Serialize, Deserialize)]
//! pub struct Foo { pub resource_url: Option<String>, ... }
//! ```
//!
//! Semantics:
//! - container: emits one `#[serde(rename_all = "...", <forwarded args>)]`,
//!   skipping keys already present in a manual `#[serde(...)]` on the item;
//! - members: emits `#[serde(rename = "...")]` only where the policy differs
//!   from what the container rule alone would produce (acronym words, or an
//!   explicit `rename(...)` entry) — a manual field-level `rename` always wins
//!   and is left untouched;
//! - fields: with `skip_none` (default), every `Option<...>` field without its
//!   own `skip_serializing_if` and without `flatten` gets
//!   `skip_serializing_if = "Option::is_none"`.
//!
//! A fully custom `fn(&str) -> String` rename cannot be evaluated at macro
//! expansion time (same limitation as serde-rs/serde#2852): use the acronym
//! dictionary plus the declarative `rename(...)` map, or keep a manual
//! `#[serde(rename = "...")]` on the single member that needs it.

#![forbid(unsafe_code)]

use proc_macro::TokenStream;
use quote::quote;
use syn::{Attribute, Ident, Item, LitStr, Type, parse_macro_input};

mod case;
mod policy;

use case::RenameRule;
use policy::Policy;

// ==== Proc-macro entry point ====

#[proc_macro_attribute]
pub fn rest_json(attr: TokenStream, item: TokenStream) -> TokenStream {
    let policy = match Policy::parse(attr) {
        Ok(policy) => policy,
        Err(err) => return err.to_compile_error().into(),
    };
    let item = parse_macro_input!(item as Item);
    match expand(policy, item) {
        Ok(tokens) => tokens.into(),
        Err(err) => err.to_compile_error().into(),
    }
}

// ==== Expansion ====

fn expand(policy: Policy, mut item: Item) -> syn::Result<proc_macro2::TokenStream> {
    check_placement(&item)?;
    match &mut item {
        Item::Struct(item_struct) => {
            push_container_attr(&policy, &mut item_struct.attrs);
            for field in item_struct.fields.iter_mut() {
                process_member(
                    &policy,
                    &mut field.attrs,
                    field.ident.as_ref(),
                    Some(&field.ty),
                    false,
                );
            }
        }
        Item::Enum(item_enum) => {
            push_container_attr(&policy, &mut item_enum.attrs);
            for variant in item_enum.variants.iter_mut() {
                process_member(
                    &policy,
                    &mut variant.attrs,
                    Some(&variant.ident),
                    None,
                    true,
                );
                for field in variant.fields.iter_mut() {
                    process_member(
                        &policy,
                        &mut field.attrs,
                        field.ident.as_ref(),
                        Some(&field.ty),
                        false,
                    );
                }
            }
        }
        other => {
            return Err(syn::Error::new_spanned(
                other,
                "rest_json: only applies to structs and enums",
            ));
        }
    }
    Ok(quote!(#item))
}

/// `#[rest_json]` must sit above `#[derive(...)]`: attribute macros expand
/// outside-in, so the derive is still visible here; below the derive it would
/// have run already and the emitted `#[serde(...)]` attributes would be ignored.
fn check_placement(item: &Item) -> syn::Result<()> {
    let attrs = match item {
        Item::Struct(s) => &s.attrs,
        Item::Enum(e) => &e.attrs,
        other => {
            return Err(syn::Error::new_spanned(
                other,
                "rest_json: only applies to structs and enums",
            ));
        }
    };
    let derives_serde = attrs.iter().any(|attr: &Attribute| {
        if !attr.path().is_ident("derive") {
            return false;
        }
        let mut found = false;
        let _ = attr.parse_nested_meta(|meta: syn::meta::ParseNestedMeta| {
            if let Some(last) = meta.path.segments.last() {
                if last.ident == "Serialize" || last.ident == "Deserialize" {
                    found = true;
                }
            }
            Ok(())
        });
        found
    });
    if derives_serde {
        Ok(())
    } else {
        Err(syn::Error::new_spanned(
            item,
            "rest_json: place #[rest_json(...)] above #[derive(... Serialize, Deserialize ...)]",
        ))
    }
}

// ==== Container-level #[serde(...)] emission ====

/// Idents of the top-level keys of every existing container-level `#[serde(...)]`,
/// plus whether a `rename_all` is already present (serde rejects duplicates).
fn container_serde_keys(attrs: &[Attribute]) -> (Vec<String>, bool) {
    let mut keys = Vec::new();
    let mut has_rename_all = false;
    for attr in attrs
        .iter()
        .filter(|a: &&Attribute| a.path().is_ident("serde"))
    {
        let _ = attr.parse_nested_meta(|meta: syn::meta::ParseNestedMeta| {
            if let Some(ident) = meta.path.get_ident() {
                if ident == "rename_all" {
                    has_rename_all = true;
                }
                keys.push(ident.to_string());
            }
            Ok(())
        });
    }
    (keys, has_rename_all)
}

/// Builds the single container-level `#[serde(...)]` attribute to add and pushes
/// it, unless the policy adds nothing beyond what manual attributes already say.
fn push_container_attr(policy: &Policy, attrs: &mut Vec<Attribute>) {
    let (keys, has_rename_all) = container_serde_keys(attrs);
    let mut parts: Vec<proc_macro2::TokenStream> = Vec::new();
    if let Some(rule) = policy.rename_all {
        if !has_rename_all {
            let lit = LitStr::new(rule_name(rule), proc_macro2::Span::call_site());
            parts.push(quote!(rename_all = #lit));
        }
    }
    for forwarded in &policy.forwarded {
        // Re-parse the forwarded meta to read its top-level key.
        let Ok(meta) = syn::parse2::<syn::Meta>(forwarded.clone()) else {
            continue;
        };
        let key = meta.path().get_ident().map(|i: &syn::Ident| i.to_string());
        if key
            .as_deref()
            .is_none_or(|k: &str| !keys.contains(&k.to_string()))
        {
            parts.push(forwarded.clone());
        }
    }
    if !parts.is_empty() {
        attrs.push(syn::parse_quote!(#[serde(#(#parts),*)]));
    }
}

fn rule_name(rule: RenameRule) -> &'static str {
    match rule {
        RenameRule::Lowercase => "lowercase",
        RenameRule::Uppercase => "UPPERCASE",
        RenameRule::PascalCase => "PascalCase",
        RenameRule::CamelCase => "camelCase",
        RenameRule::SnakeCase => "snake_case",
        RenameRule::ScreamingSnakeCase => "SCREAMING_SNAKE_CASE",
        RenameRule::KebabCase => "kebab-case",
        RenameRule::ScreamingKebabCase => "SCREAMING-KEBAB-CASE",
    }
}

// ==== Member-level attribute emission ====

/// Adds the policy's `rename` / `skip_serializing_if` attributes to one member
/// (struct field or enum variant), leaving manual `#[serde(...)]` untouched.
fn process_member(
    policy: &Policy,
    attrs: &mut Vec<Attribute>,
    ident: Option<&Ident>,
    ty: Option<&Type>,
    is_variant: bool,
) {
    let (has_rename, has_skip, has_flatten) = member_serde_flags(attrs);
    if let Some(ident) = ident {
        let raw = ident.to_string();
        let id = raw.strip_prefix("r#").unwrap_or(&raw).to_string();
        if !has_rename {
            if let Some(wire) = policy.renames.get(&id) {
                let lit = LitStr::new(wire, ident.span());
                attrs.push(syn::parse_quote!(#[serde(rename = #lit)]));
            } else if let Some(rule) = policy.rename_all {
                let plain = rule.apply_plain(&id, is_variant);
                let acronym = rule.apply_acronyms(&id, is_variant, &policy.acronyms);
                if acronym != plain {
                    let lit = LitStr::new(&acronym, ident.span());
                    attrs.push(syn::parse_quote!(#[serde(rename = #lit)]));
                }
            }
        }
    }
    if policy.skip_none && !is_variant && !has_skip && !has_flatten && ty.is_some_and(is_option) {
        attrs.push(syn::parse_quote!(#[serde(skip_serializing_if = "Option::is_none")]));
    }
}

/// Flags of the member's existing `#[serde(...)]` attributes: explicit `rename`,
/// any `skip_serializing_if`, and `flatten` (incompatible with skip_serializing_if).
fn member_serde_flags(attrs: &[Attribute]) -> (bool, bool, bool) {
    let mut has_rename = false;
    let mut has_skip = false;
    let mut has_flatten = false;
    for attr in attrs
        .iter()
        .filter(|a: &&Attribute| a.path().is_ident("serde"))
    {
        let _ = attr.parse_nested_meta(|meta: syn::meta::ParseNestedMeta| {
            if let Some(ident) = meta.path.get_ident() {
                match ident.to_string().as_str() {
                    "rename" => has_rename = true,
                    "skip_serializing_if" => has_skip = true,
                    "flatten" => has_flatten = true,
                    _ => {}
                }
            }
            Ok(())
        });
    }
    (has_rename, has_skip, has_flatten)
}

fn is_option(ty: &Type) -> bool {
    match ty {
        // Look through references: `&Option<T>` fields are Option fields too.
        Type::Reference(reference) => is_option(&reference.elem),
        Type::Path(type_path) if type_path.qself.is_none() => type_path
            .path
            .segments
            .last()
            .is_some_and(|seg: &syn::PathSegment| seg.ident == "Option"),
        _ => false,
    }
}
