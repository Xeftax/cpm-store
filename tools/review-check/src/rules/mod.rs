//! Registre des règles du linter. Une règle = un périmètre d'items AST + un statut
//! (violation/conforme). L'enregistrement est factorisé ici : ajouter une règle =
//! un fichier dans `rules/` + une ligne dans `all()`.

pub mod delegate_same_name;
pub mod helper_in_fn;
pub mod main_rs_thin;
pub mod manual_serde_impl;
pub mod newtype_pub;

use syn::spanned::Spanned;
use syn::{ImplItem, Item, ItemFn, ItemImpl, ItemStruct};

/// Un item candidat, avec son statut.
pub struct Candidate {
    pub line: usize,
    pub violation: bool,
}

pub trait Rule {
    fn id(&self) -> &'static str;
    /// Tout le périmètre de la règle (conforme + violation) — sert au mode --audit.
    fn candidates(&self, ast: &syn::File) -> Vec<Candidate>;
}

/// Registre unique des règles.
pub fn all() -> Vec<Box<dyn Rule>> {
    vec![
        Box::new(newtype_pub::NewtypePub),
        Box::new(helper_in_fn::HelperInFn),
        Box::new(manual_serde_impl::ManualSerdeImpl),
        Box::new(delegate_same_name::DelegateSameName),
        Box::new(main_rs_thin::MainRsThin),
    ]
}

// ── Helpers d'itération sur l'AST (factorisation des match génériques) ──────

pub fn line_of<T: Spanned>(n: &T) -> usize {
    n.span().start().line
}

pub fn structs(ast: &syn::File) -> impl Iterator<Item = &ItemStruct> {
    ast.items.iter().filter_map(|i| match i {
        Item::Struct(s) => Some(s),
        _ => None,
    })
}

pub fn fns(ast: &syn::File) -> impl Iterator<Item = &ItemFn> {
    ast.items.iter().filter_map(|i| match i {
        Item::Fn(f) => Some(f),
        _ => None,
    })
}

pub fn impls(ast: &syn::File) -> impl Iterator<Item = &ItemImpl> {
    ast.items.iter().filter_map(|i| match i {
        Item::Impl(imp) => Some(imp),
        _ => None,
    })
}

pub fn impl_methods(ast: &syn::File) -> impl Iterator<Item = &syn::ImplItemFn> {
    impls(ast).flat_map(|imp| {
        imp.items.iter().filter_map(|s| match s {
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
        rule.candidates(&ast)
            .into_iter()
            .filter(|c| c.violation)
            .map(|c| c.line)
            .collect()
    }

    #[test]
    fn newtype_pub_detects_pub_field_only() {
        let r = newtype_pub::NewtypePub;
        assert_eq!(violations(&r, "pub struct A(pub Vec<u8>);"), vec![1]);
        // conforme : champ privé
        let ast = syn::parse_file("struct B(Vec<u8>);").unwrap();
        assert!(r.candidates(&ast).iter().all(|c| !c.violation));
        // hors périmètre : struct nommée
        assert!(r.candidates(&syn::parse_file("struct C { x: u8 }").unwrap()).is_empty());
    }

    #[test]
    fn helper_detects_struct_in_fn_only() {
        let r = helper_in_fn::HelperInFn;
        assert_eq!(
            violations(&r, "fn f() { struct H { x: u8 } }"),
            vec![1]
        );
        assert!(violations(&r, "fn g() {}").is_empty());
        assert!(violations(&r, "struct Top;").is_empty());
    }

    #[test]
    fn manual_serde_impl_detects_serialize_impls() {
        let r = manual_serde_impl::ManualSerdeImpl;
        assert_eq!(
            violations(&r, "impl serde::Serialize for A {}"),
            vec![1]
        );
        assert_eq!(
            violations(&r, "impl<'de> Deserialize<'de> for A {}"),
            vec![1]
        );
        // impl de trait non-serde : hors périmètre
        assert!(violations(&r, "impl std::fmt::Debug for A {}").is_empty());
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
    fn delegate_detects_same_name_method_call_only() {
        let r = delegate_same_name::DelegateSameName;
        // violation : fn len(&self) { self.0.len() }  (même nom des deux côtés)
        assert_eq!(
            violations(&r, "impl A { fn len(&self) -> usize { self.0.len() } }"),
            vec![1]
        );
        // conforme : logique métier ajoutée
        assert!(violations(&r, "impl A { fn get(&self, n: &str) -> bool { self.0.contains(n) } }").is_empty());
        // conforme : nom différent de l'appel interne
        assert!(violations(&r, "impl A { fn size(&self) -> usize { self.0.len() } }").is_empty());
    }
}
