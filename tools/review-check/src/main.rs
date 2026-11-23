//! review-check — deterministic known-patterns linter (ADR 0001). Thin CLI:
//! parses args, delegates to the engine (checker) and the report (report).
//!
//! Usage:
//!   review-check [base] [ref]                  ADDED lines of the diff (default: main HEAD)
//!   review-check --all [base] [ref]            audit of ALL files
//!   review-check --audit=<rule-id> [base] [ref] full scope of one rule (ok/violation)
//!   --format=gcc                               VS Code problemMatcher output
//! Always exits 0 (warning only — blocking = compiler/tests/clippy, ADR 0001).

mod checker;
mod report;
mod rules;

use checker::Mode;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut gcc = false;
    let mut all = false;
    let mut watch_flag = false;
    let mut audit: Option<String> = None;
    let mut positional: Vec<&str> = Vec::new();
    for a in &args {
        if a == "--format=gcc" {
            gcc = true;
        } else if a == "--all" {
            all = true;
        } else if a == "--watch" {
            watch_flag = true;
        } else if let Some(id) = a.strip_prefix("--audit=") {
            audit = Some(id.to_string());
        } else {
            positional.push(a);
        }
    }
    // fixed precedence, independent of flag order: audit > watch > all > diff
    let mode = if let Some(id) = audit {
        Mode::Audit(id)
    } else if watch_flag {
        Mode::Watch
    } else if all {
        Mode::All
    } else {
        Mode::Diff
    };
    let base = positional.first().copied().unwrap_or("main");
    let refr = positional.get(1).copied().unwrap_or("HEAD");

    let root = checker::git_root();
    let cfg = checker::load_config(&root);

    if mode == Mode::Watch {
        watch(&root, &cfg, gcc);
        return;
    }

    let (findings, n_files) = checker::run(&root, &cfg, base, refr, &mode);
    let scope_desc = match &mode {
        Mode::Diff => format!("added lines of the diff {base}...{refr}"),
        Mode::All => "ALL files (full audit)".to_string(),
        Mode::Audit(id) => format!("full scope of rule {id}"),
        Mode::Watch => unreachable!(),
    };
    report::print(&findings, n_files, &mode, gcc, &scope_desc);
}

/// Watch loop: every 500ms, re-lint (All mode) if a .rs file changed
/// (mtime polling, portable). Each run is logged with a timestamp for the
/// VS Code background problemMatcher (beginsPattern "[review-check] run").
fn watch(root: &str, cfg: &checker::Config, gcc: bool) {
    use std::collections::HashMap;
    use std::time::{Duration, SystemTime, UNIX_EPOCH};

    let mut last_mtime: HashMap<String, SystemTime> = HashMap::new();
    let mut first = true;
    loop {
        let files: Vec<String> = checker::git(root, &["ls-files", "*.rs"])
            .lines()
            .map(String::from)
            .collect();
        let mut changed = first;
        for f in &files {
            if let Ok(mt) = std::fs::metadata(std::path::Path::new(root).join(f))
                .and_then(|m: std::fs::Metadata| m.modified())
            {
                if last_mtime
                    .get(f)
                    .map(|&p: &SystemTime| mt > p)
                    .unwrap_or(true)
                {
                    changed = true;
                }
                last_mtime.insert(f.clone(), mt);
            }
        }
        if changed {
            let secs = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d: Duration| d.as_secs())
                .unwrap_or(0);
            println!("[review-check] run unix={secs}");
            let (findings, n_files) = checker::run(root, cfg, "HEAD", "HEAD", &Mode::All);
            report::print(&findings, n_files, &Mode::All, gcc, "watch — all files");
        }
        first = false;
        std::thread::sleep(Duration::from_millis(500));
    }
}
