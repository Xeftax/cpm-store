//! Rule `serde-redundant-attr`: a field/variant-level `#[serde(...)]` attribute is
//! redundant when the container-level attribute already produces the same effect:
//!
//! - A: `rename = "X"` where X equals what the container's `rename_all` produces for
//!   this ident (or equals the ident itself when there is no `rename_all`). Note the
//!   wire acronym case is NOT redundant: camelCase("resource_url") is "resourceUrl",
//!   so `rename = "resourceURL"` is load-bearing, not a duplicate.
//! - B: `alias = "X"` where X equals the effective (renamed) wire name.
//! - C: a bare field-level `default` when the container already has `default` —
//!   container default wins for missing fields, so the field-level one is dead code.
//! - D: a `rename` that is NOT redundant (differs from the `rename_all` output, e.g.
//!   a wire acronym like "resourceURL") must be explained by a comment on the same
//!   line as the attribute (`#[serde(rename = "resourceURL")] // wire ...`) or by a
//!   `///` doc comment on the member — otherwise the next reader assumes it is a
//!   duplicate of rename_all and deletes it.
//!
//! The RenameRule implementation mirrors serde_derive's rename rules (field vs
//! variant context), so the comparison is exact rather than pattern-matched.

use super::{line_of, structs, Candidate, Rule};
use syn::spanned::Spanned;
use syn::{Attribute, Field, Item, ItemEnum, LitStr, Variant};

// ==== Rule entry point ====

pub struct SerdeRedundantAttr;

// ==== RenameRule: serde_derive-compatible rename rules ====

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum RenameRule {
    Lowercase,
    Uppercase,
    PascalCase,
    CamelCase,
    SnakeCase,
    ScreamingSnakeCase,
    KebabCase,
    ScreamingKebabCase,
}

impl RenameRule {
    pub fn parse(s: &str) -> Option<Self> {
        Some(match s {
            "lowercase" => Self::Lowercase,
            "UPPERCASE" => Self::Uppercase,
            "PascalCase" => Self::PascalCase,
            "camelCase" => Self::CamelCase,
            "snake_case" => Self::SnakeCase,
            "SCREAMING_SNAKE_CASE" => Self::ScreamingSnakeCase,
            "kebab-case" => Self::KebabCase,
            "SCREAMING-KEBAB-CASE" => Self::ScreamingKebabCase,
            _ => return None,
        })
    }

    pub fn apply_to_field(self, id: &str) -> String {
        match self {
            Self::Lowercase => id.to_lowercase(),
            Self::Uppercase => id.to_uppercase(),
            Self::PascalCase => id.split('_').map(capitalize).collect(),
            Self::CamelCase => id
                .split('_')
                .enumerate()
                .map(|(i, w)| if i == 0 { w.to_string() } else { capitalize(w) })
                .collect(),
            Self::SnakeCase => to_snake(id),
            Self::ScreamingSnakeCase => to_snake(id).to_uppercase(),
            Self::KebabCase => to_snake(id).replace('_', "-"),
            Self::ScreamingKebabCase => to_snake(id).to_uppercase().replace('_', "-"),
        }
    }

    pub fn apply_to_variant(self, id: &str) -> String {
        match self {
            Self::CamelCase => {
                let pascal: String = id.split('_').map(capitalize).collect();
                let mut chars = pascal.chars();
                match chars.next() {
                    Some(f) => f.to_lowercase().collect::<String>() + chars.as_str(),
                    None => pascal,
                }
            }
            _ => self.apply_to_field(id),
        }
    }
}

fn capitalize(word: &str) -> String {
    let mut chars = word.chars();
    match chars.next() {
        Some(f) => f.to_uppercase().collect::<String>() + chars.as_str(),
        None => String::new(),
    }
}

/// serde-style CamelCase -> snake_case (acronym aware): "DeletedObject" ->
/// "deleted_object", "resourceURL" -> "resource_url".
fn to_snake(id: &str) -> String {
    let chars: Vec<char> = id.chars().collect();
    let mut out = String::new();
    for (i, &c) in chars.iter().enumerate() {
        if c.is_uppercase() && i > 0 {
            let prev = chars[i - 1];
            let next_lower = chars.get(i + 1).map(|n| n.is_lowercase()).unwrap_or(false);
            if prev.is_lowercase() || prev.is_ascii_digit() || (prev.is_uppercase() && next_lower) {
                out.push('_');
            }
        }
        out.extend(c.to_lowercase());
    }
    out
}

// ==== Attribute parsing ====

#[derive(Default)]
struct ContainerAttrs {
    rename_all: Option<RenameRule>,
    default: bool,
}

#[derive(Default)]
struct FieldAttrs {
    rename: Option<String>,
    aliases: Vec<String>,
    default_bare: bool,
}

fn serde_attrs(attrs: &[Attribute]) -> impl Iterator<Item = &Attribute> {
    attrs.iter().filter(|a| a.path().is_ident("serde"))
}

fn parse_container(attr: &Attribute) -> ContainerAttrs {
    let mut cont = ContainerAttrs::default();
    let _ = attr.parse_nested_meta(|meta| {
        if meta.path.is_ident("rename_all") {
            let lit: LitStr = meta.value()?.parse()?;
            cont.rename_all = RenameRule::parse(&lit.value());
        } else if meta.path.is_ident("default") {
            cont.default = true;
            if meta.input.peek(syn::Token![=]) {
                let _: LitStr = meta.value()?.parse()?;
            }
        } else if meta.input.peek(syn::Token![=]) {
            let _: syn::Expr = meta.input.parse()?;
        }
        Ok(())
    });
    cont
}

fn parse_field_attrs(attr: &Attribute) -> FieldAttrs {
    let mut fa = FieldAttrs::default();
    let _ = attr.parse_nested_meta(|meta| {
        if meta.path.is_ident("rename") {
            fa.rename = Some(meta.value()?.parse::<LitStr>()?.value());
        } else if meta.path.is_ident("alias") {
            fa.aliases.push(meta.value()?.parse::<LitStr>()?.value());
        } else if meta.path.is_ident("default") {
            if meta.input.peek(syn::Token![=]) {
                let _: LitStr = meta.value()?.parse()?;
            } else {
                fa.default_bare = true;
            }
        } else if meta.input.peek(syn::Token![=]) {
            let _: syn::Expr = meta.input.parse()?;
        }
        Ok(())
    });
    fa
}

fn enums(ast: &syn::File) -> impl Iterator<Item = &ItemEnum> {
    ast.items.iter().filter_map(|i| match i {
        Item::Enum(e) => Some(e),
        _ => None,
    })
}

// ==== Member checking (rules A/B/C/D) ====

fn effective_name(ident: &str, rule: Option<RenameRule>, is_variant: bool) -> String {
    let id = ident.strip_prefix("r#").unwrap_or(ident);
    match rule {
        Some(r) if is_variant => r.apply_to_variant(id),
        Some(r) => r.apply_to_field(id),
        None => id.to_string(),
    }
}

/// True when the attribute is explained by a // comment: on one of the attribute's
/// own lines (trailing comment) or on the single line right after it when rustfmt
/// wrapped a too-long trailing comment there. Comments are not in the AST, so this
/// reads the source around the attribute's line span.
fn attr_has_comment(attr: &Attribute, src: &str) -> bool {
    let start = attr.span().start().line;
    let end = attr.span().end().line;
    let lines: Vec<&str> = src.lines().collect();
    let in_attr = |i: usize| (i + 1) >= start && (i + 1) <= end;
    let wrapped = end < lines.len() && lines[end].trim_start().starts_with("//");
    lines
        .iter()
        .enumerate()
        .any(|(i, l)| in_attr(i) && l.contains("//"))
        || wrapped
}

fn check_member(
    out: &mut Vec<Candidate>,
    cont: &ContainerAttrs,
    attrs: &[Attribute],
    ident: &str,
    is_variant: bool,
    src: &str,
) {
    let eff = effective_name(ident, cont.rename_all, is_variant);
    let has_doc = attrs.iter().any(|a| a.path().is_ident("doc"));
    for attr in serde_attrs(attrs) {
        let line = line_of(attr);
        let fa = parse_field_attrs(attr);
        if let Some(r) = &fa.rename {
            // rule A: rename == effective name -> redundant. rule D: a load-bearing
            // rename (differs from the rename_all output) must be commented.
            let documented = has_doc || attr_has_comment(attr, src);
            out.push(Candidate {
                line,
                violation: r == &eff || !documented,
            });
        }
        for a in &fa.aliases {
            out.push(Candidate {
                line,
                violation: a == &eff,
            });
        }
        if fa.default_bare && cont.default {
            out.push(Candidate {
                line,
                violation: true,
            });
        }
    }
}

fn field_ident(field: &Field, index: usize) -> String {
    field
        .ident
        .as_ref()
        .map(|i| i.to_string())
        .unwrap_or_else(|| index.to_string())
}

impl Rule for SerdeRedundantAttr {
    fn id(&self) -> &'static str {
        "serde-redundant-attr"
    }

    fn candidates(&self, ast: &syn::File, src: &str) -> Vec<Candidate> {
        let mut out = Vec::new();
        for s in structs(ast) {
            let cont = serde_attrs(&s.attrs).map(parse_container).fold(
                ContainerAttrs::default(),
                |mut acc, c| {
                    acc.rename_all = acc.rename_all.or(c.rename_all);
                    acc.default |= c.default;
                    acc
                },
            );
            for (i, field) in s.fields.iter().enumerate() {
                check_member(&mut out, &cont, &field.attrs, &field_ident(field, i), false, src);
            }
        }
        for e in enums(ast) {
            let cont = serde_attrs(&e.attrs).map(parse_container).fold(
                ContainerAttrs::default(),
                |mut acc, c| {
                    acc.rename_all = acc.rename_all.or(c.rename_all);
                    acc.default |= c.default;
                    acc
                },
            );
            for v in &e.variants {
                check_member(&mut out, &cont, &v.attrs, &v.ident.to_string(), true, src);
                let variant: &Variant = v;
                for (i, field) in variant.fields.iter().enumerate() {
                    check_member(&mut out, &cont, &field.attrs, &field_ident(field, i), false, src);
                }
            }
        }
        out
    }
}
