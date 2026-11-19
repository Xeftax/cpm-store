//! Règle `manual-delegation-methods` : périmètre = toutes les méthodes d'impl ;
//! violation si le corps est un SEUL appel de méthode de MEME NOM sur le champ
//! interne (`fn foo(&self) { self.x.foo(..) }`) — c'est Deref qui devrait le générer.

use super::{impl_methods, line_of, Candidate, Rule};
use syn::{Expr, Stmt};

pub struct DelegateSameName;

impl Rule for DelegateSameName {
    fn id(&self) -> &'static str {
        "manual-delegation-methods"
    }

    fn candidates(&self, ast: &syn::File, _src: &str) -> Vec<Candidate> {
        impl_methods(ast)
            .map(|m: &syn::ImplItemFn| Candidate {
                line: line_of(&m.sig.ident),
                violation: is_same_name_delegation(m),
            })
            .collect()
    }
}

fn is_same_name_delegation(m: &syn::ImplItemFn) -> bool {
    if m.block.stmts.len() != 1 {
        return false;
    }
    matches!(&m.block.stmts[0], Stmt::Expr(Expr::MethodCall(mc), None)
        if matches!(&*mc.receiver, Expr::Field(f)
            if matches!(&*f.base, Expr::Path(p) if p.path.is_ident("self")))
        && mc.method == m.sig.ident)
}
