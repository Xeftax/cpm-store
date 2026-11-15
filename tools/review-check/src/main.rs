//! review-check — linter déterministe de known-patterns (ADR 0001).
//!
//! La détection est du CODE sur l'AST (syn), pas une regex : chaque règle est une
//! fonction déterministe, comme un lint clippy. Le TOML (.vibe/review/known-patterns.toml)
//! ne fournit que la config (id, scope, severity, exclude_files, message, occurrences) ;
//! rule/applies_to/when_not_applicable/bad_example/good_example y sont de la DOC.
//!
//! Usage: review-check [base] [ref]   (défaut: main HEAD)
//! Check uniquement les items dont la ligne de début est une ligne AJOUTÉE du diff.
//! Toujours exit 0 (warning only — bloquant = compilateur/tests/clippy, ADR 0001).

use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::Path;
use std::process::Command;

use syn::spanned::Spanned;
use syn::{Expr, Fields, Item, ItemImpl, ItemStruct, Stmt, Visibility};

#[derive(serde::Deserialize)]
struct Config {
    pattern: Vec<Pattern>,
}

#[derive(serde::Deserialize)]
struct Pattern {
    id: String,
    scope: String,
    #[serde(default)]
    severity: String,
    #[serde(default)]
    exclude_files: Vec<String>,
    #[serde(default)]
    message: String,
    // champs doc (rule, applies_to, when_not_applicable, bad_example, good_example,
    // occurrences) : ignorés par le checker, lus par les humains/LLM.
}

fn git(root: &str, args: &[&str]) -> String {
    let out = Command::new("git")
        .args(args)
        .current_dir(root)
        .output()
        .expect("git failed");
    String::from_utf8_lossy(&out.stdout).into_owned()
}

/// Lignes ajoutées du diff base...ref, par fichier .rs : {path: {numéros de ligne}}.
fn added_lines(root: &str, base: &str, refr: &str) -> HashMap<String, HashSet<usize>> {
    let diff = git(root, &["diff", &format!("{base}...{refr}"), "--", "*.rs"]);
    let mut map: HashMap<String, HashSet<usize>> = HashMap::new();
    let mut cur: Option<String> = None;
    let mut lineno = 0usize;
    for line in diff.lines() {
        if let Some(p) = line.strip_prefix("+++ b/") {
            cur = Some(p.to_string());
            map.insert(p.to_string(), HashSet::new());
        } else if line.starts_with("@@") {
            lineno = line
                .split("+")
                .nth(1)
                .and_then(|s| s.split(',').next())
                .and_then(|n| n.parse().ok())
                .unwrap_or(0);
        } else if let Some(c) = &cur {
            if line.starts_with('+') && !line.starts_with("+++") {
                if let Some(set) = map.get_mut(c) {
                    set.insert(lineno);
                }
                lineno += 1;
            } else if !line.starts_with('-') {
                lineno += 1;
            }
        }
    }
    map
}

fn scope_match(scope: &str, path: &str) -> bool {
    // "crates/**/*.rs" -> préfixe "crates/" + suffixe ".rs"
    let prefix = scope
        .trim_end_matches("**/*.rs")
        .trim_end_matches("**/*")
        .trim_end_matches('*');
    path.starts_with(prefix) && path.ends_with(".rs")
}

fn line_of<T: Spanned>(node: &T) -> usize {
    node.span().start().line
}

// ── Règles déterministes (AST) ──────────────────────────────────────────────

/// newtype-pub-with-delegation : struct tuple avec au moins un champ `pub`.
fn is_newtype_pub(s: &ItemStruct) -> bool {
    matches!(s.fields, Fields::Unnamed(_))
        && s.fields
            .iter()
            .any(|f| matches!(f.vis, Visibility::Public(_)))
}

/// manual-serde-impl : bloc impl d'un trait dont le nom contient "Serialize".
fn is_manual_serde_impl(imp: &ItemImpl) -> bool {
    imp.trait_
        .as_ref()
        .and_then(|(_, path, _)| path.segments.last())
        .map(|seg| seg.ident.to_string().contains("Serialize"))
        .unwrap_or(false)
}

/// serde-helper-identity : une struct déclarée DANS le bloc d'une fonction.
fn has_helper_struct_in_fn(ast: &syn::File) -> Vec<usize> {
    let mut lines = Vec::new();
    for item in &ast.items {
        if let Item::Fn(f) = item {
            for stmt in &f.block.stmts {
                if let Stmt::Item(Item::Struct(s)) = stmt {
                    lines.push((line_of(&s.ident), s.ident.to_string()));
                }
            }
        }
    }
    lines.iter().map(|(l, _)| *l).collect()
}

/// manual-delegation-methods : méthode `fn foo(&self) { self.<inner>.foo(...) }`
/// (corps = un seul appel de méthode de MEME NOM sur le champ interne).
fn delegate_same_name_lines(ast: &syn::File) -> Vec<usize> {
    let mut lines = Vec::new();
    for item in &ast.items {
        if let Item::Impl(imp) = item {
            for sub in &imp.items {
                if let syn::ImplItem::Fn(m) = sub {
                    if m.block.stmts.len() == 1 {
                        if let Stmt::Expr(Expr::MethodCall(mc), None) = &m.block.stmts[0] {
                            let receiver_is_self_field = matches!(
                                &*mc.receiver,
                                Expr::Field(f)
                                    if matches!(&*f.base, Expr::Path(p) if p.path.is_ident("self"))
                            );
                            if receiver_is_self_field && mc.method == m.sig.ident {
                                lines.push(line_of(&m.sig.ident));
                            }
                        }
                    }
                }
            }
        }
    }
    lines
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let base = args.get(1).map(String::as_str).unwrap_or("main");
    let refr = args.get(2).map(String::as_str).unwrap_or("HEAD");

    let root = git(".", &["rev-parse", "--show-toplevel"]).trim().to_string();
    let cfg_path = Path::new(&root).join(".vibe/review/known-patterns.toml");
    let cfg: Config = toml::from_str(&fs::read_to_string(&cfg_path).expect("known-patterns.toml"))
        .expect("parse known-patterns.toml");

    let files = added_lines(&root, base, refr);
    let mut hits = 0usize;

    for (path, added) in &files {
        let src = git(&root, &["show", &format!("{refr}:{path}")]);
        let ast = match syn::parse_file(&src) {
            Ok(a) => a,
            Err(_) => continue,
        };
        for p in &cfg.pattern {
            if !scope_match(&p.scope, path) || p.exclude_files.iter().any(|e| e == path) {
                continue;
            }
            let rule_lines: Vec<usize> = match p.id.as_str() {
                "newtype-pub-with-delegation" => ast
                    .items
                    .iter()
                    .filter_map(|it| match it {
                        Item::Struct(s) if is_newtype_pub(s) => Some(line_of(&s.ident)),
                        _ => None,
                    })
                    .collect(),
                "manual-serde-impl" => ast
                    .items
                    .iter()
                    .filter_map(|it| match it {
                        Item::Impl(imp) if is_manual_serde_impl(imp) => Some(line_of(imp)),
                        _ => None,
                    })
                    .collect(),
                "serde-helper-identity" => has_helper_struct_in_fn(&ast),
                "manual-delegation-methods" => delegate_same_name_lines(&ast),
                _ => continue,
            };
            for line in rule_lines {
                if !added.contains(&line) {
                    continue; // que les items ajoutés par le diff
                }
                let snippet = src.lines().nth(line - 1).unwrap_or("").trim();
                println!("warning[{}] {}:{}: {}", p.id, path, line, snippet);
                println!("    -> {}", p.message);
                hits += 1;
            }
        }
    }

    println!(
        "\n{hits} known-pattern(s) en warning sur les items ajoutés du diff {base}...{refr} \
         ({} fichiers .rs modifiés) — exit 0 (warning only, ADR 0001)",
        files.len()
    );
}
