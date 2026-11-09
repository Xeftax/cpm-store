#!/usr/bin/env bash
# Shared Rust lint invocation for the pre-commit hook, the session hooks (--hook) and the
# `lint-rust` check — the Rust counterpart of `lint-python.sh`.
#
# Usage: lint-rust.sh [--check | --fix | --hook]
#
# With no flag the script picks the mode from where it runs: `--check` when `CI=true`
# (every GitHub runner sets it), `--fix` otherwise. So CI, pre-commit and a session hook
# run the same command with no argument of their own, and a developer's terminal fixes.
#
# --check: `cargo fmt --all -- --check`, then `cargo clippy --workspace --all-targets --
# -D warnings` captured to clippy.txt (the check's artifact). Both run even if the first
# fails, and the script exits non-zero if either did.
#
# --fix: `cargo fmt --all`, then `cargo clippy --fix` (machine-applicable suggestions only),
# then the `--check` pair again so the hook reports what it could not fix.
#
# --hook: a session hook's call, payload on stdin — see lib/hook-mode.sh. `cargo fmt
# --check` over the whole workspace: it is seconds, and scoping it to uncommitted files
# would need per-file editions. Clippy stays out of the hook — a full workspace lint on
# every turn is the cost that gets hooks uninstalled; CI runs it.
#
# A tree with no `Cargo.toml` at the root passes silently: the base declares every
# language, and a Python repo receives this script only to find it inert.
set -uo pipefail

if [[ "${1:-}" == "--hook" ]]; then
  source "$(dirname "${BASH_SOURCE[0]}")/lib/hook-mode.sh"
  hook_enter || exit 0
  [[ -f Cargo.toml ]] || exit 0
  cargo fmt --all -- --check
  hook_exit "$?"
fi

[[ -f Cargo.toml ]] || exit 0

mode="${1:-}"
if [[ -z "$mode" ]]; then
  if [[ "${CI:-}" == "true" ]]; then mode=--check; else mode=--fix; fi
fi

if [[ "$mode" == "--fix" ]]; then
  cargo fmt --all
  cargo clippy --workspace --all-targets --fix --allow-dirty --allow-staged --quiet || true
fi

fmt_status=0
cargo fmt --all -- --check || fmt_status=$?

# No `--message-format=github` here: that value is ruff's, cargo's own `--message-format`
# accepts only human/short/json/…, and past the `--` clippy-driver rejects it outright.
# GitHub annotates clippy's output from the JSON diagnostics cargo emits by default on
# Actions runners well enough; the check's verdict does not depend on it.
clippy_args=(clippy --workspace --all-targets -- -D warnings)
if [[ "$mode" == "--check" ]]; then
  cargo "${clippy_args[@]}" > clippy.txt 2>&1
  clippy_status=$?
  cat clippy.txt
else
  cargo "${clippy_args[@]}" || clippy_status=$?
fi

[[ $fmt_status -eq 0 && $clippy_status -eq 0 ]]
