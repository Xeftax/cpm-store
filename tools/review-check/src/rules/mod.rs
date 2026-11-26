//! Registry of the linter rules. A rule = a scope of AST items + a status
//! (violation/compliant). Registration is factored here: adding a rule =
//! one file in `rules/` + one line in `all()`.

pub mod closure_params_typed;
pub mod delegate_same_name;
pub mod duplicate_fn_bodies;
pub mod enum_declaration_order;
pub mod file_sections;
pub mod helper_in_fn;
pub mod main_rs_thin;
pub mod manual_serde_impl;
pub mod match_arms_are_dispatch;
pub mod match_not_if_else_on_enum;
pub mod newtype_pub;
pub mod no_bool_mode_params;
pub mod no_cross_fn_arm_duplication;
pub mod serde_redundant_attr;
pub mod thematic_clusters;
pub mod total_vs_domain_contract;
pub mod vendored_byte_exact;

use syn::spanned::Spanned;
use syn::{ImplItem, Item, ItemFn, ItemImpl, ItemStruct};

/// A candidate item, with its status.
#[derive(Debug)]
pub struct Candidate {
    pub line: usize,
    pub violation: bool,
}

pub trait Rule {
    fn id(&self) -> &'static str;
    /// The whole scope of the rule (compliant + violation) — used by the --audit mode.
    /// `src` = source of the file (for rules that read comments, e.g. sections).
    fn candidates(&self, ast: &syn::File, src: &str) -> Vec<Candidate>;
}

/// Single registry of the rules.
pub fn all() -> Vec<Box<dyn Rule>> {
    vec![
        Box::new(closure_params_typed::ClosureParamsTyped),
        Box::new(serde_redundant_attr::SerdeRedundantAttr),
        Box::new(newtype_pub::NewtypePub),
        Box::new(helper_in_fn::HelperInFn),
        Box::new(manual_serde_impl::ManualSerdeImpl),
        Box::new(delegate_same_name::DelegateSameName),
        Box::new(main_rs_thin::MainRsThin),
        Box::new(duplicate_fn_bodies::DuplicateFnBodies),
        Box::new(enum_declaration_order::EnumDeclarationOrder),
        Box::new(file_sections::FileSections),
        Box::new(thematic_clusters::ThematicClusters),
        Box::new(match_arms_are_dispatch::MatchArmsAreDispatch),
        Box::new(match_not_if_else_on_enum::MatchNotIfElseOnEnum),
        Box::new(no_bool_mode_params::NoBoolModeParams),
        Box::new(no_cross_fn_arm_duplication::NoCrossFnArmDuplication),
        Box::new(total_vs_domain_contract::TotalVsDomainContract),
        Box::new(vendored_byte_exact::VendoredByteExact),
    ]
}

// ── AST iteration helpers (factoring of the generic matches) ──────

pub fn line_of<T: Spanned>(n: &T) -> usize {
    n.span().start().line
}

/// Recognized section banner: `// ==== Title ====` (section) or
/// `// ---- Title ----` (sub-section) — 3+ identical signs after `// `.
pub fn is_section_banner(l: &str) -> bool {
    let t = l.trim_start();
    t.starts_with("// ===") || t.starts_with("// ---")
}

pub fn structs(ast: &syn::File) -> impl Iterator<Item = &ItemStruct> {
    ast.items.iter().filter_map(|i: &Item| match i {
        Item::Struct(s) => Some(s),
        _ => None,
    })
}

pub fn fns(ast: &syn::File) -> impl Iterator<Item = &ItemFn> {
    ast.items.iter().filter_map(|i: &Item| match i {
        Item::Fn(f) => Some(f),
        _ => None,
    })
}

pub fn impls(ast: &syn::File) -> impl Iterator<Item = &ItemImpl> {
    ast.items.iter().filter_map(|i: &Item| match i {
        Item::Impl(imp) => Some(imp),
        _ => None,
    })
}

pub fn impl_methods(ast: &syn::File) -> impl Iterator<Item = &syn::ImplItemFn> {
    impls(ast).flat_map(|imp: &ItemImpl| {
        imp.items.iter().filter_map(|s: &ImplItem| match s {
            ImplItem::Fn(m) => Some(m),
            _ => None,
        })
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn violations(rule: &dyn Rule, src: &str) -> Vec<usize> {
        let ast = syn::parse_file(src).unwrap();
        rule.candidates(&ast, src)
            .into_iter()
            .filter(|c: &Candidate| c.violation)
            .map(|c: Candidate| c.line)
            .collect()
    }

    #[test]
    fn newtype_pub_detects_pub_field_only() {
        let r = newtype_pub::NewtypePub;
        assert_eq!(violations(&r, "pub struct A(pub Vec<u8>);"), vec![1]);
        // compliant: private field
        let ast = syn::parse_file("struct B(Vec<u8>);").unwrap();
        assert!(r
            .candidates(&ast, "struct B(Vec<u8>);")
            .iter()
            .all(|c| !c.violation));
        // out of scope: named struct
        assert!(r
            .candidates(
                &syn::parse_file("struct C { x: u8 }").unwrap(),
                "struct C { x: u8 }"
            )
            .is_empty());
    }

    #[test]
    fn helper_detects_struct_in_fn_only() {
        let r = helper_in_fn::HelperInFn;
        assert_eq!(violations(&r, "fn f() { struct H { x: u8 } }"), vec![1]);
        assert!(violations(&r, "fn g() {}").is_empty());
        assert!(violations(&r, "struct Top;").is_empty());
        // the Helper can also live in an impl method (attribute.rs case, PR #3)
        assert_eq!(
            violations(&r, "impl A { fn f() { struct H { x: u8 } } }"),
            vec![1]
        );
    }

    #[test]
    fn manual_serde_impl_detects_serialize_impls() {
        let r = manual_serde_impl::ManualSerdeImpl;
        assert_eq!(violations(&r, "impl serde::Serialize for A {}"), vec![1]);
        assert_eq!(
            violations(&r, "impl<'de> Deserialize<'de> for A {}"),
            vec![1]
        );
        // non-serde trait impl: out of scope
        assert!(violations(&r, "impl std::fmt::Debug for A {}").is_empty());
    }

    #[test]
    fn duplicate_fn_bodies_flags_same_shape() {
        let r = duplicate_fn_bodies::DuplicateFnBodies;
        // message_context / direction: same body up to NAME/type -> 2 violations
        let src = r#"
impl AttributeList {
    fn message_context(&self) -> Option<MessageContext> {
        self.first_value("Message-Context").map(MessageContext::parse)
    }
    fn direction(&self) -> Option<Direction> {
        self.first_value("Direction").map(Direction::parse)
    }
    fn unique(&self) -> usize { self.0.len() * 2 + 1 }
}
"#;
        let v = violations(&r, src);
        assert_eq!(v.len(), 2, "both duplicated fns must be flagged: {v:?}");
    }

    #[test]
    fn file_sections_flags_big_file_without_banners() {
        let r = file_sections::FileSections;
        let big = (0..12)
            .map(|i: i32| format!("fn f{i}() {{}}"))
            .collect::<Vec<_>>()
            .join("\n");
        assert_eq!(violations(&r, &big).len(), 1);
        let with_banner = format!("// ==== Section ====\n{big}");
        assert!(violations(&r, &with_banner).is_empty());
        let with_dash_banner = format!("// ---- Section ----\n{big}");
        assert!(violations(&r, &with_dash_banner).is_empty());
        let small = "fn a() {}\nfn b() {}".to_string();
        assert!(violations(&r, &small).is_empty());
    }

    #[test]
    fn thematic_clusters_group_call_chains() {
        let r = thematic_clusters::ThematicClusters;
        // get -> values -> first_value -> message_context: one chain = one cluster of 4
        let src = r#"
impl L {
    fn get(&self, n: &str) -> Option<u8> { self.0.iter().find(|a| *a == 1) }
    fn values(&self, n: &str) -> Option<u8> { self.get(n).map(|a| a + 1) }
    fn first_value(&self, n: &str) -> Option<u8> { self.values(n).map(|v| v + 2) }
    fn message_context(&self) -> Option<u8> { self.first_value("x").map(|v| v + 3) }
    fn lonely(&self) -> u8 { 42 }
}
"#;
        let ast = syn::parse_file(src).unwrap();
        let c = r.candidates(&ast, src);
        assert_eq!(c.len(), 1, "a single cluster of size >= 3: {c:?}");
        assert!(c[0].violation, "no // ==== banner above -> violation");
        // with a banner above -> compliant (// ==== section or // ---- sub-section)
        let with_banner = format!("// ==== Lookup ====\n{src}");
        let ast2 = syn::parse_file(&with_banner).unwrap();
        assert!(r
            .candidates(&ast2, &with_banner)
            .iter()
            .all(|c| !c.violation));
    }

    #[test]
    fn main_rs_thin_flags_definitions_in_main() {
        let r = main_rs_thin::MainRsThin;
        // violation: struct + impl in main.rs
        let src = "mod x;\nfn main() {}\nstruct Config { a: u8 }\nimpl Config {}\n";
        assert_eq!(violations(&r, src).len(), 2);
        // compliant: thin CLI (mod + fn main only)
        let ok = "mod checker;\nfn main() {}\n";
        assert!(violations(&r, ok).is_empty());
    }

    #[test]
    fn closure_params_typed_flags_untyped_params() {
        let r = closure_params_typed::ClosureParamsTyped;
        // untyped param -> violation at the closure line
        assert_eq!(violations(&r, "fn f() { let g = |a| a + 1; }"), vec![1]);
        assert_eq!(
            violations(&r, "fn f(xs: &[i32]) { xs.iter().find(|a| *a == 1); }"),
            vec![1]
        );
        // typed param -> compliant
        assert!(violations(&r, "fn f() { let g = |a: i32| a + 1; }").is_empty());
        assert!(violations(
            &r,
            "fn f(xs: &[i32]) { xs.iter().find(|a: &&i32| **a == 1); }"
        )
        .is_empty());
        // wildcard -> compliant (nothing to type)
        assert!(violations(&r, "fn f() { let g = |_| 1; }").is_empty());
        // no params -> no candidate
        assert!(violations(&r, "fn f() { let g = || 1; }").is_empty());
        // tuple pattern must be typed as a whole
        assert_eq!(
            violations(
                &r,
                "fn f(pairs: &[(i32, i32)]) { pairs.iter().find(|(k, _)| *k == 1); }"
            ),
            vec![1]
        );
        assert!(violations(
            &r,
            "fn f(pairs: &[(i32, i32)]) { pairs.iter().find(|(k, _): &(i32, i32)| k == &1); }"
        )
        .is_empty());
    }

    #[test]
    fn rename_rule_matches_serde_outputs() {
        use serde_redundant_attr::RenameRule;
        let cc = RenameRule::parse("camelCase").unwrap();
        assert_eq!(cc.apply_to_field("resource_url"), "resourceUrl");
        assert_eq!(cc.apply_to_field("type"), "type");
        assert_eq!(cc.apply_to_field("last_mod_seq"), "lastModSeq");
        assert_eq!(cc.apply_to_variant("DeletedObject"), "deletedObject");
        assert_eq!(cc.apply_to_variant("ResetBox"), "resetBox");
        assert_eq!(RenameRule::parse("verbatim"), None);
    }

    #[test]
    fn serde_redundant_attr_flags_rename_alias_default() {
        let r = serde_redundant_attr::SerdeRedundantAttr;
        // rename == camelCase(name) and alias == name are redundant; the wire-acronym
        // rename "resourceURL" differs from camelCase("resource_url") = "resourceUrl"
        // and must NOT be flagged.
        let src = r#"
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct S {
    #[serde(rename = "name", alias = "name")]
    name: String,
    /// Wire name "resourceURL" (spec acronym; camelCase would give "resourceUrl").
    #[serde(rename = "resourceURL")]
    resource_url: String,
}
"#;
        assert_eq!(
            violations(&r, src).len(),
            2,
            "rename+alias on 'name' flagged, resourceURL not"
        );
        // identity rename without rename_all is redundant too
        let src_id = "#[derive(Serialize)] struct S2 { #[serde(rename = \"x\")] x: u32 }";
        assert_eq!(violations(&r, src_id).len(), 1);
        // container default makes a bare field default dead
        let src_def =
            "#[derive(Serialize, Default)] #[serde(default)] struct T { #[serde(default)] x: u32 }";
        assert_eq!(violations(&r, src_def).len(), 1);
        // no container default -> field default is meaningful
        let src_nodef = "#[derive(Serialize)] struct U { #[serde(default)] x: u32 }";
        assert!(violations(&r, src_nodef).is_empty());
        // enum variant rename equal to rename_all(variant) is redundant
        let src_enum = r#"
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
enum E {
    #[serde(rename = "resetBox")]
    ResetBox,
    #[serde(rename = "other")]
    OtherThing,
}
"#;
        assert_eq!(
            violations(&r, src_enum).len(),
            2,
            "ResetBox: rename == camelCase(variant) -> redundant (rule A); OtherThing: rename != camelCase and no doc -> undocumented (rule D)"
        );
        // rule D: a load-bearing rename (differs from rename_all output) needs a ///
        // comment on the member; a redundant one is flagged regardless of the doc
        let src_doc = r#"
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct W {
    #[serde(rename = "resourceURL")] // wire "resourceURL": spec caps acronym, not camelCase "resourceUrl"
    resource_url: String,
    /// Wire name "notifyURL" (spec acronym; camelCase would give "notifyUrl").
    #[serde(rename = "notifyURL")]
    notify_url: String,
    #[serde(rename = "callbackURL")]
    callback_url: String,
}
"#;
        let v = violations(&r, src_doc);
        assert_eq!(
            v.len(),
            1,
            "trailing-comment and /// renames ok, undocumented callbackURL flagged: {v:?}"
        );
    }

    #[test]
    fn delegate_detects_same_name_method_call_only() {
        let r = delegate_same_name::DelegateSameName;
        // violation: fn len(&self) { self.0.len() }  (same name on both sides)
        assert_eq!(
            violations(&r, "impl A { fn len(&self) -> usize { self.0.len() } }"),
            vec![1]
        );
        // compliant: added business logic
        assert!(violations(
            &r,
            "impl A { fn get(&self, n: &str) -> bool { self.0.contains(n) } }"
        )
        .is_empty());
        // compliant: name different from the inner call
        assert!(violations(&r, "impl A { fn size(&self) -> usize { self.0.len() } }").is_empty());
    }
}
