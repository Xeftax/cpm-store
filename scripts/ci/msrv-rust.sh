#!/usr/bin/env bash
# The MSRV check: compile the workspace with exactly the `rust-version` the workspace
# `Cargo.toml` declares, so a dependency bump that quietly raised the real MSRV fails here
# rather than on a downstream consumer's older toolchain. CI and the merge queue only
# (profile `ci`): installing a second toolchain is no pre-commit hook's job.
#
# A tree with no `Cargo.toml`, or one whose workspace manifest declares no `rust-version`,
# passes silently — there is no MSRV promise to hold.
set -euo pipefail

[[ -f Cargo.toml ]] || exit 0

msrv="$(sed -n 's/^rust-version *= *"\([^"]*\)".*/\1/p' Cargo.toml | head -n 1)"
[[ -n "$msrv" ]] || exit 0

if command -v rustup > /dev/null; then
  # `cargo +<toolchain>` only works when cargo IS rustup's shim; a Homebrew cargo rejects
  # it, so drive the pinned toolchain through rustup explicitly.
  rustup toolchain install "$msrv" --profile minimal
  # --locked: the committed Cargo.lock is the MSRV source of truth; without it cargo
  # re-resolves and may pick deps whose rust-version exceeds the MSRV (encoding_rs 0.8.44…)
  rustup run "$msrv" cargo check --workspace --locked
else
  # No rustup on this machine (Homebrew cargo, say): check with the installed toolchain.
  # The pin itself is enforced where rustup exists — CI installs it in the setup branch.
  echo "no rustup: checking with the installed toolchain against MSRV $msrv" >&2
  cargo check --workspace --locked
fi
