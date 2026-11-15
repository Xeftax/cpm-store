//! review-check — linter déterministe de known-patterns (ADR 0001).
//!
//! La détection est du CODE sur l'AST (syn), pas une regex : chaque règle est une
//! fonction déterministe, comme un lint clippy. Le TOML (.vibe/review/known-patterns.toml)
//! ne fournit que la config (id, scope, severity, exclude_files, message, occurrences) ;
//! rule/applies_to/when_not_applicable/bad_example/good_example y sont de la DOC.
//!
//! Usage:
//!   review-check [base] [ref]                 check des lignes AJOUTÉES du diff (défaut: main HEAD)
//!   review-check --all [base] [ref]           check de TOUS les fichiers (audit complet)
//!   review-check --audit=<rule-id> [base] [ref]  liste tout le périmètre de la règle,
//!                                             avec statut ok/violation (réversibilité)
//!   --format=gcc                              sortie problemMatcher VS Code:
//!                                             path:line:1: warning: message (rule-id)
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

#[derive(PartialEq)]
enum Mode {
    Diff,
    All,
    Audit(String),
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
                .split('+')
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
//
// Chaque règle = une fonction `candidates` qui retourne TOUS les items du périmètre
// avec un statut : true = violation, false = conforme. Le mode diff/all n'émet que les
// violations ; le mode --audit liste tout le périmètre avec son statut (réversibilité :
// pour changer une règle, on voit partout où elle s'applique, conforme ou non).

fn is_newtype_pub(s: &ItemStruct) -> bool {
    s.fields
        .iter()
        .any(|f| matches!(f.vis, Visibility::Public(_)))
}

fn rule_candidates(id: &str, ast: &syn::File) -> Vec<(usize, bool)> {
    match id {
        // périmètre = tous les tuple structs ; violation si champ pub
        "newtype-pub-with-delegation" => ast
            .items
            .iter()
            .filter_map(|it| match it {
                Item::Struct(s) if matches!(s.fields, Fields::Unnamed(_)) => {
                    Some((line_of(&s.ident), is_newtype_pub(s)))
                }
                _ => None,
            })
            .collect(),
        // périmètre = toutes les fonctions ; violation si struct déclarée dedans
        "serde-helper-identity" => {
            let mut out = Vec::new();
            for item in &ast.items {
                if let Item::Fn(f) = item {
                    let has = f
                        .block
                        .stmts
                        .iter()
                        .any(|s| matches!(s, Stmt::Item(Item::Struct(_))));
                    out.push((line_of(&f.sig.ident), has));
                }
            }
            out
        }
        // périmètre = tous les impls de traits Serialize ; violation = à vérifier
        "manual-serde-impl" => ast
            .items
            .iter()
            .filter_map(|it| match it {
                Item::Impl(imp)
                    if imp
                        .trait_
                        .as_ref()
                        .and_then(|(_, path, _)| path.segments.last())
                        .map(|seg| seg.ident.to_string().contains("Serialize"))
                        .unwrap_or(false) =>
                {
                    Some((line_of(imp), true))
                }
                _ => None,
            })
            .collect(),
        // périmètre = toutes les méthodes d'impl ; violation si délégation same-name
        "manual-delegation-methods" => {
            let mut out = Vec::new();
            for item in &ast.items {
                if let Item::Impl(imp) = item {
                    for sub in &imp.items {
                        if let syn::ImplItem::Fn(m) = sub {
                            let delegates = m.block.stmts.len() == 1
                                && matches!(&m.block.stmts[0], Stmt::Expr(Expr::MethodCall(mc), None)
                                    if matches!(&*mc.receiver, Expr::Field(f)
                                        if matches!(&*f.base, Expr::Path(p) if p.path.is_ident("self")))
                                    && mc.method == m.sig.ident);
                            out.push((line_of(&m.sig.ident), delegates));
                        }
                    }
                }
            }
            out
        }
        _ => Vec::new(),
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut mode = Mode::Diff;
    let mut gcc = false;
    let mut positional: Vec<&str> = Vec::new();
    for a in &args {
        if a == "--format=gcc" {
            gcc = true;
        } else if a == "--all" {
            mode = Mode::All;
        } else if let Some(id) = a.strip_prefix("--audit=") {
            mode = Mode::Audit(id.to_string());
        } else {
            positional.push(a);
        }
    }
    let base = positional.first().copied().unwrap_or("main");
    let refr = positional.get(1).copied().unwrap_or("HEAD");

    let root = git(".", &["rev-parse", "--show-toplevel"]).trim().to_string();
    let cfg_path = Path::new(&root).join(".vibe/review/known-patterns.toml");
    let cfg: Config = toml::from_str(&fs::read_to_string(&cfg_path).expect("known-patterns.toml"))
        .expect("parse known-patterns.toml");

    let added = added_lines(&root, base, refr);
    let files: Vec<String> = if mode == Mode::All {
        git(&root, &["ls-files", "*.rs"]).lines().map(String::from).collect()
    } else {
        let mut v: Vec<String> = added.keys().cloned().collect();
        v.sort();
        v
    };

    let mut hits = 0usize;
    for path in &files {
        for p in &cfg.pattern {
            if !scope_match(&p.scope, path) || p.exclude_files.iter().any(|e| e == path) {
                continue;
            }
            let in_audit = matches!(&mode, Mode::Audit(id) if id == &p.id);
            if matches!(&mode, Mode::Audit(id) if id != &p.id) {
                continue;
            }
            let src = if mode == Mode::All {
                fs::read_to_string(Path::new(&root).join(path)).unwrap_or_default()
            } else {
                git(&root, &["show", &format!("{refr}:{path}")])
            };
            let ast = match syn::parse_file(&src) {
                Ok(a) => a,
                Err(_) => continue,
            };
            for (line, violation) in rule_candidates(&p.id, &ast) {
                let in_diff = mode == Mode::All || added.get(path).map(|s| s.contains(&line)).unwrap_or(false);
                let emit = match &mode {
                    Mode::Diff => violation && in_diff,
                    Mode::All => violation,
                    Mode::Audit(_) => true, // tout le périmètre, avec statut
                };
                if !emit {
                    continue;
                }
                let snippet = src.lines().nth(line - 1).unwrap_or("").trim();
                if gcc {
                    if violation {
                        println!("{path}:{line}:1: warning: {} ({})", p.message, p.id);
                    }
                } else if matches!(&mode, Mode::Audit(_)) {
                    let status = if violation { "VIOLATION" } else { "ok" };
                    println!("{status} [{}] {}:{}: {}", p.id, path, line, snippet);
                } else if violation {
                    println!("warning[{}] {}:{}: {}", p.id, path, line, snippet);
                    println!("    -> {}", p.message);
                }
                if violation {
                    hits += 1;
                }
            }
        }
    }

    let scope_desc = match &mode {
        Mode::Diff => format!("lignes ajoutées du diff {base}...{refr}"),
        Mode::All => "TOUS les fichiers (audit complet)".to_string(),
        Mode::Audit(id) => format!("périmètre complet de la règle {id}"),
    };
    println!(
        "\n{hits} violation(s) — {scope_desc} ({} fichiers .rs) — exit 0 (warning only, ADR 0001)",
        files.len()
    );
}
