//! Règle `thematic-clusters` : le sémantique « qui va ensemble » = le graphe d'appels
//! intra-fichier. Chaque fonction qui appelle une autre fonction du même fichier crée
//! une arête ; les composantes connexes (union-find) de taille >= 3 forment des groupes
//! thématiques. Un groupe sans bannière `// ====` au-dessus de son premier membre
//! manque de section -> violation.
//!
//! Ex: get -> values -> first_value -> message_context/direction = un cluster "lookup
//! + accesseurs typés" (attribute.rs, PR #3).

use super::{fns, impl_methods, line_of, Candidate, Rule};
use std::collections::HashMap;
use syn::visit::Visit;

const MIN_CLUSTER: usize = 3;

pub struct ThematicClusters;

impl Rule for ThematicClusters {
    fn id(&self) -> &'static str {
        "thematic-clusters"
    }

    fn candidates(&self, ast: &syn::File, src: &str) -> Vec<Candidate> {
        // 1. toutes les fonctions du fichier : nom -> ligne
        let mut fn_lines: HashMap<String, usize> = HashMap::new();
        for f in fns(ast) {
            fn_lines.insert(f.sig.ident.to_string(), line_of(&f.sig.ident));
        }
        for m in impl_methods(ast) {
            fn_lines.insert(m.sig.ident.to_string(), line_of(&m.sig.ident));
        }

        // 2. arêtes caller -> callee (appels résolus vers des fns du même fichier)
        let mut uf = UnionFind::new(&fn_lines);
        let mut visit_fn = |block: &syn::Block, caller: &str| {
            let mut c = CallCollector { calls: Vec::new() };
            c.visit_block(block);
            for callee in c.calls {
                if fn_lines.contains_key(&callee) && callee != caller {
                    uf.union(caller, &callee);
                }
            }
        };
        for f in fns(ast) {
            visit_fn(&f.block, &f.sig.ident.to_string());
        }
        for m in impl_methods(ast) {
            visit_fn(&m.block, &m.sig.ident.to_string());
        }

        // 3. composantes connexes de taille >= MIN_CLUSTER
        let clusters = uf.components(MIN_CLUSTER);
        let src_lines: Vec<&str> = src.lines().collect();
        clusters
            .iter()
            .map(|members: &Vec<String>| {
                let first_line = members
                    .iter()
                    .map(|n: &String| fn_lines[n])
                    .min()
                    .unwrap_or(1);
                // bannière de section dans les 5 lignes précédant le premier membre ?
                let has_banner = (first_line.saturating_sub(5)..first_line)
                    .filter_map(|i: usize| i.checked_sub(1).and_then(|j: usize| src_lines.get(j)))
                    .any(|l: &&str| super::is_section_banner(l));
                Candidate {
                    line: first_line,
                    violation: !has_banner,
                }
            })
            .collect()
    }
}

/// Collecte les noms appelés (méthodes + fonctions) dans un bloc.
struct CallCollector {
    calls: Vec<String>,
}

impl<'ast> Visit<'ast> for CallCollector {
    fn visit_expr_method_call(&mut self, e: &'ast syn::ExprMethodCall) {
        self.calls.push(e.method.to_string());
        syn::visit::visit_expr_method_call(self, e);
    }
    fn visit_expr_call(&mut self, e: &'ast syn::ExprCall) {
        if let syn::Expr::Path(p) = &*e.func {
            if let Some(seg) = p.path.segments.last() {
                self.calls.push(seg.ident.to_string());
            }
        }
        syn::visit::visit_expr_call(self, e);
    }
}

/// Union-find sur les noms de fonctions.
struct UnionFind {
    parent: HashMap<String, String>,
}

impl UnionFind {
    fn new(names: &HashMap<String, usize>) -> Self {
        UnionFind {
            parent: names
                .keys()
                .map(|k: &String| (k.clone(), k.clone()))
                .collect(),
        }
    }
    fn find(&mut self, x: &str) -> String {
        let mut root = x.to_string();
        while self.parent[&root] != root {
            root = self.parent[&root].clone();
        }
        root
    }
    fn union(&mut self, a: &str, b: &str) {
        let ra = self.find(a);
        let rb = self.find(b);
        if ra != rb {
            self.parent.insert(ra, rb);
        }
    }
    fn components(&mut self, min_size: usize) -> Vec<Vec<String>> {
        let mut groups: HashMap<String, Vec<String>> = HashMap::new();
        let names: Vec<String> = self.parent.keys().cloned().collect();
        for n in names {
            let r = self.find(&n);
            groups.entry(r).or_default().push(n);
        }
        groups
            .into_values()
            .filter(|g: &Vec<String>| g.len() >= min_size)
            .collect()
    }
}
