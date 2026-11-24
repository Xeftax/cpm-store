---
name: model-struct-owner
description: "OWNER of type declarations of the cpm-core domain model (struct/enum, pub visibility, derives, fields, factoring of repetitive methods via macro_rules!, organization into sections). NEVER run inline: when relevant, spawn a subagent (Vibe: agents.spawn, instructions = this file). Trigger when adding/editing/reviewing a struct or enum in crates/cpm-core/src/model/**, or when 2+ methods share the same body up to a name/type. MUST BE USED before and after any PR touching model type declarations."
user-invocable: false
---

# model-struct-owner

Owner of the "domain model type declarations" domain (cpm-core). Reference case:
PR #3, `crates/cpm-core/src/model/attribute.rs` (`Attribute`, `AttributeList`).

## Dual role

- **Advise BEFORE**: "I am declaring a new type" -> which derives, which visibility, which fields.
- **Review AFTER**: "review this declarations diff" -> verdict against the invariants.

## Read first (on every invocation, never from memory)

- `crates/cpm-core/src/model/*.rs` (attribute.rs, kind.rs, folder.rs, mod.rs)
- `crates/cpm-core/src/model/mod.rs` for the `pub use` (re-exports)

## Invariants — Do & Don't

- DO derive `Debug, Clone, PartialEq, Eq` together on data types.
- DON'T derive `Eq` if a field is `f32`/`f64` (`PartialEq` only — `NaN != NaN`).
- DO use **owned** fields only (`String`, `Vec<String>`, `u64`...): never a `&str` in
  a domain struct, or the struct needs a lifetime (`struct Borrowed<'a>`).
- DO use `pub` for the minimum needed; re-export in `mod.rs` via `pub use` rather than making
  the sub-modules themselves public when not useful.
- Lifetimes: a trait's parameter (e.g. `'de` on `Deserialize<'de>`) is **mandatory in the
  impl** if declared on the trait (error E0726 otherwise). `'static` = literals. Lifetimes
  are checked at compile time (borrow checker) and erased at runtime.
- DO document the expected JSON shape in a doc comment (`///`) above each type,
  with the spec section (REST-NMS / CPM-REST).

### newtype rule: semantic name + vehicle for impls (orphan rule)

- A newtype = `struct X(Vec<T>)` (tuple struct, `.0` field). It gives a name to an existing
  type AND a home for traits on foreign types: `impl Serialize for Vec<Attribute>` is
  forbidden (E0117, orphan rule — foreign trait and type), `impl Serialize for AttributeList`
  is allowed because `AttributeList` is local. That is why PR #3 writes the
  `{"attribute": [...]}` wrapper by hand.
- Choose newtype vs named struct for the JSON mapping knowingly:
  - **named struct + derive + Deref = best of both worlds** when the JSON has a named key:
    `struct AttributeList { #[serde(default, deserialize_with = "super::one_or_many")] attribute: Vec<Attribute> }`
    -> the derive produces `{"attribute": [...]}` by itself (proven with cargo/serde:
    serialize, deserialize, missing field -> empty vec) + `impl Deref<Target = Vec<Attribute>>`
    generates `len()/iter()/is_empty()`, private field included. No more manual serde impl.
  - newtype `X(pub Vec<T>)`: convenient tuple construction (`X(vec![...])`), but the derive
    is **transparent** (serializes `[...]` without a key) -> manual serde impl for the
    wrapper. PR #3 case (`AttributeList(pub Vec<Attribute>)` + manual impl lines 103-121).
- DO document this choice in the type's doc comment.

### rule for exposing a newtype's content

- DO use `impl std::ops::Deref<Target = Vec<T>>` when you want the **entire** collection API
  (`len()`, `iter()`, `is_empty()`, `get()`...) **generated automatically** — private field
  as a bonus. Compiled proof: ex13. Caveat: Deref also exposes `push/remove/clear` — avoid it
  if an invariant must be protected (e.g. name uniqueness §5.3.2.6).
- DON'T hand-write pure delegations (`len/iter/is_empty`) when `Deref` generates them —
  that is dead duplication. Hand-write only the **business** methods (e.g. `get`
  case-insensitive §5.3.2.5).
- If you filter the API (invariant on insertion): private field + chosen methods, NO Deref.
- A `pub .0` field = assumed full transparency (callers do `x.0.len()`) — acceptable
  but less readable than `x.len()` via Deref.
- DO `impl From<Vec<T>> for X` (+ `new`) to keep construction ergonomic with a named
  struct: `X::from(vec![...])` or `vec![...].into()` (proven, ex16).
- **Deref is all-or-nothing**: `type Target` is a concrete type, and deref coercion exposes
  ALL its public methods — you cannot pass a list of names. For an explicit subset:
  hand-written methods if few, otherwise the macro `delegate! { len -> usize, is_empty -> bool }` (explicit list + generation, proven ex17 — `push` stays unavailable,
  E0599), or the `ambassador` crate (`#[derive(Delegate)]` on a trait) for heavy declarative use.

### organization rule: one type file = thematic sections

- DO split a type file into commented sections: declaration / generic lookup /
  spec accessors / (de)serialization. PR #3 case: `AttributeList` refactored into 3 sections.
  (Distinct concept from the method factoring below.)

### factoring rule: duplicated methods -> generation

- RULE: 2+ methods with exactly the same body up to a name/type -> generate them with a
  declarative `macro_rules!` rather than copy-paste. PR #3 case: `message_context()` /
  `direction()` = both `first_value(NOM).map(T::parse)` -> macro `typed_attribute!`
  (2 declaration lines per attribute, doc comment preserved).
- The macro lives in the type's file (a single entry point); lift it into `mod.rs`
  only if another module reuses it.
- Alternative for 10+ cases: a trait `SpecAttribute { const NAME: &'static str; fn parse(&str) -> Self; }`
  - `fn typed<V: SpecAttribute>(&self) -> Option<V>`. For 2-3 cases, the macro wins (methods
    are named, discoverable, with doc comments) — do not over-engineer.

## Report

- Cite the `file:line` read during this invocation. Two-part verdict: **proven**
  (command + output) / **not proven** (and why).
