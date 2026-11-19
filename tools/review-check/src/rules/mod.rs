//! Registre des règles du linter. Une règle = un périmètre d'items AST + un statut
//! (violation/conforme). L'enregistrement est factorisé ici : ajouter une règle =
//! un fichier dans `rules/` + une ligne dans `all()`.

pub mod closure_params_typed;
pub mod delegate_same_name;
pub mod duplicate_fn_bodies;
pub mod file_sections;
pub mod helper_in_fn;
pub mod main_rs_thin;
pub mod manual_serde_impl;
pub mod newtype_pub;
pub mod thematic_clusters;

use syn::spanned::Spanned;
use syn::{ImplItem, Item, ItemFn, ItemImpl, ItemStruct};

/// Un item candidat, avec son statut.
#[derive(Debug)]
pub struct Candidate {
    pub line: usize,
    pub violation: bool,
}

pub trait Rule {
    fn id(&self) -> &'static str;
    /// Tout le périmètre de la règle (conforme + violation) — sert au mode --audit.
    /// `src` = source du fichier (pour les règles qui lisent les commentaires, ex. sections).
    fn candidates(&self, ast: &syn::File, src: &str) -> Vec<Candidate>;
}

/// Registre unique des règles.
pub fn all() -> Vec<Box<dyn Rule>> {
    vec![
        Box::new(closure_params_typed::ClosureParamsTyped),
        Box::new(newtype_pub::NewtypePub),
        Box::new(helper_in_fn::HelperInFn),
        Box::new(manual_serde_impl::ManualSerdeImpl),
        Box::new(delegate_same_name::DelegateSameName),
        Box::new(main_rs_thin::MainRsThin),
        Box::new(duplicate_fn_bodies::DuplicateFnBodies),
        Box::new(file_sections::FileSections),
        Box::new(thematic_clusters::ThematicClusters),
    ]
}

// ── Helpers d'itération sur l'AST (factorisation des match génériques) ──────

pub fn line_of<T: Spanned>(n: &T) -> usize {
    n.span().start().line
}

/// Bannière de section reconnue : `// ==== Titre ====` (section) ou
/// `// ---- Titre ----` (sous-section) — 3+ signes identiques après `// `.
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
        // conforme : champ privé
        let ast = syn::parse_file("struct B(Vec<u8>);").unwrap();
        assert!(r
            .candidates(&ast, "struct B(Vec<u8>);")
            .iter()
            .all(|c| !c.violation));
        // hors périmètre : struct nommée
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
        // le Helper peut aussi vivre dans une méthode d'impl (cas attribute.rs PR #3)
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
        // impl de trait non-serde : hors périmètre
        assert!(violations(&r, "impl std::fmt::Debug for A {}").is_empty());
    }

    #[test]
    fn duplicate_fn_bodies_flags_same_shape() {
        let r = duplicate_fn_bodies::DuplicateFnBodies;
        // message_context / direction : même corps à NOM/type près -> 2 violations
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
        assert_eq!(
            v.len(),
            2,
            "les deux fns dupliquées doivent être flaguées: {v:?}"
        );
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
        // get -> values -> first_value -> message_context : une chaîne = un cluster de 4
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
        assert_eq!(c.len(), 1, "un seul cluster de taille >= 3: {c:?}");
        assert!(
            c[0].violation,
            "pas de bannière // ==== au-dessus -> violation"
        );
        // avec une bannière au-dessus -> conforme (section // ==== ou sous-section // ----)
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
        // violation : struct + impl dans main.rs
        let src = "mod x;\nfn main() {}\nstruct Config { a: u8 }\nimpl Config {}\n";
        assert_eq!(violations(&r, src).len(), 2);
        // conforme : CLI mince (mod + fn main uniquement)
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
    fn delegate_detects_same_name_method_call_only() {
        let r = delegate_same_name::DelegateSameName;
        // violation : fn len(&self) { self.0.len() }  (même nom des deux côtés)
        assert_eq!(
            violations(&r, "impl A { fn len(&self) -> usize { self.0.len() } }"),
            vec![1]
        );
        // conforme : logique métier ajoutée
        assert!(violations(
            &r,
            "impl A { fn get(&self, n: &str) -> bool { self.0.contains(n) } }"
        )
        .is_empty());
        // conforme : nom différent de l'appel interne
        assert!(violations(&r, "impl A { fn size(&self) -> usize { self.0.len() } }").is_empty());
    }
}
