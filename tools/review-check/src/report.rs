//! Checker output: human format (default) or gcc (VS Code problemMatcher).

use crate::checker::{Finding, Mode};

pub fn print(findings: &[Finding], n_files: usize, mode: &Mode, gcc: bool, scope_desc: &str) {
    let violations = findings.iter().filter(|f: &&Finding| f.violation).count();
    for f in findings {
        if gcc {
            if f.violation {
                println!(
                    "{}:{}:1: {}: {} ({})",
                    f.path, f.line, f.severity, f.message, f.rule_id
                );
            }
        } else if matches!(mode, Mode::Audit(_)) {
            let status = if f.violation { "VIOLATION" } else { "ok" };
            println!(
                "{status} [{}] {}:{}: {}",
                f.rule_id, f.path, f.line, f.snippet
            );
        } else if f.violation {
            println!(
                "warning[{}] {}:{}: {}",
                f.rule_id, f.path, f.line, f.snippet
            );
            println!("    -> {}", f.message);
        }
    }
    println!(
        "\n{violations} violation(s) — {scope_desc} ({n_files} .rs files) — exit 0 (warning only, ADR 0001)"
    );
}
