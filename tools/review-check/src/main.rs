//! review-check — linter déterministe de known-patterns (ADR 0001). CLI mince :
//! parse les args, délègue au moteur (checker) et au rapport (report).
//!
//! Usage:
//!   review-check [base] [ref]                  lignes AJOUTÉES du diff (défaut: main HEAD)
//!   review-check --all [base] [ref]            audit de TOUS les fichiers
//!   review-check --audit=<rule-id> [base] [ref] périmètre complet d'une règle (ok/violation)
//!   --format=gcc                               sortie problemMatcher VS Code
//! Toujours exit 0 (warning only — bloquant = compilateur/tests/clippy, ADR 0001).

mod checker;
mod report;
mod rules;

use checker::Mode;

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

    let root = checker::git_root();
    let cfg = checker::load_config(&root);
    let (findings, n_files) = checker::run(&root, &cfg, base, refr, &mode);

    let scope_desc = match &mode {
        Mode::Diff => format!("lignes ajoutées du diff {base}...{refr}"),
        Mode::All => "TOUS les fichiers (audit complet)".to_string(),
        Mode::Audit(id) => format!("périmètre complet de la règle {id}"),
    };
    report::print(&findings, n_files, &mode, gcc, &scope_desc);
}
