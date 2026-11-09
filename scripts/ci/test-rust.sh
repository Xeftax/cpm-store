#!/usr/bin/env bash
# Shared `cargo test` invocation for the `test-rust` check — the Rust counterpart of
# `test-python.sh`. CI and the merge queue only (profile `ci`): a workspace test run is no
# pre-commit hook's job, so there is no `--hook` mode here.
#
# A tree with no `Cargo.toml` at the root passes silently: the base declares every
# language, and a Python repo receives this script only to find it inert.
set -euo pipefail

[[ -f Cargo.toml ]] || exit 0

exec cargo test --workspace "$@"
