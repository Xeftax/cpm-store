//! Moteur du checker : git, diff, config TOML, exécution des règles, modes.
//! Toute la logique d'orchestration est ici ; les règles vivent dans `rules/`.

use std::collections::{HashMap, HashSet};
use std::path::Path;
use std::process::Command;

use crate::rules::{self, Candidate};

#[derive(serde::Deserialize)]
pub struct Config {
    pub pattern: Vec<Pattern>,
}

#[derive(serde::Deserialize)]
pub struct Pattern {
    pub id: String,
    pub scope: String,
    #[serde(default)]
    pub severity: String,
    #[serde(default)]
    pub exclude_files: Vec<String>,
    #[serde(default)]
    pub message: String,
    // champs doc (rule, applies_to, when_not_applicable, bad_example, good_example,
    // occurrences) : ignorés par le checker, lus par les humains/LLM.
}

#[derive(PartialEq)]
pub enum Mode {
    Diff,
    All,
    Audit(String),
    Watch, // boucle infinie : re-lint quand un .rs change (poll mtime)
}

pub struct Finding {
    pub rule_id: String,
    pub path: String,
    pub line: usize,
    pub violation: bool,
    pub snippet: String,
    pub message: String,
    pub severity: String,
}

pub fn git(root: &str, args: &[&str]) -> String {
    let out = Command::new("git")
        .args(args)
        .current_dir(root)
        .output()
        .expect("git failed");
    String::from_utf8_lossy(&out.stdout).into_owned()
}

pub fn git_root() -> String {
    git(".", &["rev-parse", "--show-toplevel"])
        .trim()
        .to_string()
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

pub fn scope_match(scope: &str, path: &str) -> bool {
    // "**/main.rs" -> suffixe ; "**/*.rs" -> wildcard '*' + extension
    if let Some(suffix) = scope.strip_prefix("**/") {
        if let Some(ext) = suffix.strip_prefix('*') {
            return path.ends_with(ext);
        }
        return path.ends_with(suffix);
    }
    let prefix = scope
        .trim_end_matches("**/*.rs")
        .trim_end_matches("**/*")
        .trim_end_matches('*');
    path.starts_with(prefix) && path.ends_with(".rs")
}

pub fn load_config(root: &str) -> Config {
    let path = Path::new(root).join(".vibe/review/known-patterns.toml");
    toml::from_str(&std::fs::read_to_string(path).expect("known-patterns.toml"))
        .expect("parse known-patterns.toml")
}

/// Exécute toutes les règles sur les fichiers concernés. Retourne tous les findings.
pub fn run(root: &str, cfg: &Config, base: &str, refr: &str, mode: &Mode) -> (Vec<Finding>, usize) {
    let added = added_lines(root, base, refr);
    let files: Vec<String> = match mode {
        Mode::All | Mode::Audit(_) => {
            let mut v: Vec<String> = git(root, &["ls-files", "*.rs"])
                .lines()
                .map(String::from)
                .collect();
            v.sort();
            v
        }
        _ => {
            let mut v: Vec<String> = added.keys().cloned().collect();
            v.sort();
            v
        }
    };

    let mut findings = Vec::new();
    for path in &files {
        for p in &cfg.pattern {
            if !scope_match(&p.scope, path) || p.exclude_files.iter().any(|e| e == path) {
                continue;
            }
            if let Mode::Audit(id) = mode {
                if id != &p.id {
                    continue;
                }
            }
            let src = match mode {
                // All/Audit lisent le working tree ; seul le mode Diff lit le ref git
                Mode::All | Mode::Audit(_) | Mode::Watch => {
                    std::fs::read_to_string(Path::new(root).join(path)).unwrap_or_default()
                }
                Mode::Diff => git(root, &["show", &format!("{refr}:{path}")]),
            };
            let ast = match syn::parse_file(&src) {
                Ok(a) => a,
                Err(_) => continue,
            };
            let rule = rules::all().into_iter().find(|r| r.id() == p.id);
            let Some(rule) = rule else { continue };
            for Candidate { line, violation } in rule.candidates(&ast, &src) {
                let in_diff = match mode {
                    Mode::All | Mode::Audit(_) | Mode::Watch => true,
                    Mode::Diff => added.get(path).map(|s| s.contains(&line)).unwrap_or(false),
                };
                let emit_violation = violation && in_diff;
                let emit = match mode {
                    Mode::Diff => emit_violation,
                    Mode::All | Mode::Watch => violation,
                    Mode::Audit(_) => true,
                };
                // soupape par ligne : `// review: ignore <rule-id>` sur la ligne du
                // finding ou celle juste au-dessus (voir review-memory-owner)
                let marker = format!("review: ignore {}", p.id);
                let ignored = violation
                    && (line.saturating_sub(2)..line).any(|idx| {
                        src.lines()
                            .nth(idx)
                            .map(|l| l.contains(&marker))
                            .unwrap_or(false)
                    });
                if emit && !ignored {
                    findings.push(Finding {
                        rule_id: p.id.clone(),
                        path: path.clone(),
                        line,
                        violation,
                        snippet: src.lines().nth(line - 1).unwrap_or("").trim().to_string(),
                        message: p.message.clone(),
                        severity: p.severity.clone(),
                    });
                }
            }
        }
    }
    (findings, files.len())
}
