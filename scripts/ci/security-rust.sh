#!/usr/bin/env bash
# Shared cargo-deny invocation for the `security-rust` check — licenses, RUSTSEC advisories
# and duplicate-version bans over the dependency tree, read from `deny.toml` at the repo
# root. The dependency graph is the supply chain a compiled repo ships, so this is a gate
# (pre-commit and PR included), like the SAST checks.
#
# Usage: security-rust.sh [--hook]
#
# --hook: a session hook's call, payload on stdin — see lib/hook-mode.sh. Runs the full
# `cargo deny check` when cargo-deny is installed, and passes silently when it is not: a
# hook on a machine without the tool must not print errors for a tool the repo never
# installed there (CI installs it in the `setup = "rust"` branch of `_check.yml`).
#
# In `--check`/CI mode the report is captured to deny-report.txt (the check's artifact);
# in --hook mode nothing is written to the working tree.
#
# A tree with no `Cargo.toml` at the root passes silently: the base declares every
# language, and a Python repo receives this script only to find it inert.
set -uo pipefail

if [[ "${1:-}" == "--hook" ]]; then
  source "$(dirname "${BASH_SOURCE[0]}")/lib/hook-mode.sh"
  hook_enter || exit 0
  [[ -f Cargo.toml ]] || exit 0
  command -v cargo-deny > /dev/null || exit 0
  cargo deny check
  hook_exit "$?"
fi

[[ -f Cargo.toml ]] || exit 0

if ! command -v cargo-deny > /dev/null; then
  # Local fallback: CI installs the binary via taiki-e/install-action; a developer's
  # machine gets the cargo install, once, then cached by cargo.
  cargo install cargo-deny --locked --quiet
fi

if [[ "${CI:-}" == "true" ]]; then
  cargo deny check > deny-report.txt 2>&1
  status=$?
  cat deny-report.txt
  exit "$status"
fi

cargo deny check "$@"
