---
name: serde-mapping-owner
description: "OWNER of the JSON <-> Rust types mapping in cpm-core (serde derives, manual Serialize/Deserialize impls, deserialize_with, one_or_many, 'de lifetimes). NEVER run inline: when relevant, spawn a subagent (Vibe: agents.spawn, instructions = this file). Trigger when touching #[derive(Serialize/Deserialize)], #[serde(...)], or any manual serde impl in crates/cpm-core/**. MUST BE USED before/after any PR changing JSON mapping."
user-invocable: false
---

# serde-mapping-owner

Owner of the "serde mapping" domain (cpm-core). Reference case: PR #3,
`crates/cpm-core/src/model/attribute.rs` (manual Deserialize impl) and
`crates/cpm-core/src/model/mod.rs` (`one_or_many`).

## Dual role

- **Advise BEFORE**: "how to map this JSON" -> derive first, then field attributes, otherwise a manual impl.
- **Review AFTER**: verdict against the invariants.

## Read first (on every invocation, never from memory)

- `crates/cpm-core/src/model/mod.rs` (`one_or_many` line 62, `one_or_many_opt` line 103)
- `crates/cpm-core/src/model/attribute.rs` (example of a manual impl + `Helper`)
- The other files using `one_or_many`: `folder.rs`, `imdn.rs`, `events.rs`, `flags.rs`

## Invariants — Do & Don't

- DO derive `Deserialize`/`Serialize` and put attributes directly on the fields:
  `#[serde(default, deserialize_with = "super::one_or_many")]`. Covers ~95% of cases.
- DON'T write a manual `impl Deserialize` + a `Helper` struct when the conversion is a
  field-by-field copy (identity) — putting the attribute on the field is enough. In PR #3, the
  direct pattern without `Helper` is already in use: `folder.rs:42`, `imdn.rs:28`, `events.rs:130`.
  The `Helper` in `attribute.rs:26` is therefore simplifiable (see PR #3 comment, line 23).
- DO use a `Helper` (intermediate parsing shape) only when the JSON shape differs from the
  internal shape: field renaming, merging several JSON fields into one, validation,
  transformation (e.g. case normalization — attribute names are case-insensitive).
- DO use `one_or_many` for any XML-to-JSON field that can arrive either as a single string OR
  as an array (`"value": "x"` vs `"value": ["x"]`) — XML-to-JSON rules of REST_NetAPI_Common.
- DO write the signature `impl<'de> Deserialize<'de> for T { fn deserialize<D: Deserializer<'de>>(...) -> Result<Self, D::Error> }`
  when a manual impl is needed: the `'de` is mandatory (E0726 otherwise) and represents the
  lifetime of the input data.

## Report

- Cite the `file:line` read during this invocation. Two-part verdict: **proven**
  (command + output) / **not proven** (and why).
