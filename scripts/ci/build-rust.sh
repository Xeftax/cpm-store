#!/usr/bin/env bash
# Shared Rust build invocation for the `build-rust` check: `cargo build --workspace` (the
# compile a missing dependency fails, which a test-only run can hide behind a dev extra) and
# `cargo doc --workspace --no-deps` (a broken intra-doc link or missing docs fail the build
# of the published crate). CI and the merge queue only (profile `ci`).
#
# A tree with no `Cargo.toml` at the root passes silently: the base declares every
# language, and a Python repo receives this script only to find it inert.
set -euo pipefail

[[ -f Cargo.toml ]] || exit 0

cargo build --workspace "$@"
cargo doc --workspace --no-deps
