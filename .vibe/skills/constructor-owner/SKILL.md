---
name: constructor-owner
description: "OWNER of constructor and public function signatures in cpm-core (new, impl Into<...> vs concrete type, Vec<T> vs impl IntoIterator). NEVER run inline: when relevant, spawn a subagent (Vibe: agents.spawn, instructions = this file). Trigger when writing/changing a `pub fn new(...)` or any public fn signature in crates/cpm-core/**. MUST BE USED before/after any PR changing a public constructor signature."
user-invocable: false
---

# constructor-owner

Owner of the "public signatures / constructors" domain (cpm-core). Reference case: PR #3,
`Attribute::new(name: impl Into<String>, value: Vec<String>)` (`attribute.rs:40`).

## Dual role

- **Advise BEFORE**: "which signature for this constructor" -> follow the call-site rule.
- **Review AFTER**: verdict against the invariants.

## Read first (on every invocation, never from memory)

- `crates/cpm-core/src/model/attribute.rs` (`Attribute::new`, `AttributeList::new`)
- All the call sites: `git grep "Attribute::new"` / `git grep "::new("` on the branch

## Invariants — Do & Don't

- DO use `name: impl Into<String>` when the call sites pass `&str` (literals): avoids a
  `.to_string()` at every call, zero cost since the struct owns the data anyway.
  Proof from PR #3: every call is `Attribute::new("Subject", ...)`.
- DON'T generalize a collection into `impl IntoIterator<Item = impl Into<String>>` "just in
  case": if the call sites already pass a `Vec<String>`, keep `Vec<String>` as-is — it is a
  `move` with no copy, whereas `collect()` would copy every element — and the public
  signature stays readable (it is the API every reader sees).
- Meta rule: **decide the signature by grepping the real call sites**, not on principle.
  "As permissive as possible" is not better: widen the API when a concrete need appears
  (YAGNI), at the call site (`.iter().map(...).collect()`) or via a dedicated named constructor.
- DO return `Self` and use the field shorthand (`value,` for `value: value`).

### multiple constructors: `new` is not magic

- `X(...)` is **not a function**: it is the struct construction syntax, reserved for
  tuple structs, and there is only one per struct (`error[E0423]` otherwise — proven ex19).
  You therefore CANNOT define several "tuple constructors".

- By contrast, **associated functions** are free to be multiple: `new(v)` (the main
  constructor), `empty()` / `Default` (empty value), and the `From<Vec<T>>` trait for `.into()`.

- DO make `new` delegate to `From::from` — one single place constructs the value
  (proven ex18: `new` + `from` + `.into()` + `empty()` coexist).

- DO keep `new` even when it only delegates to `From`: `new` is a naming convention
  (discoverable, everyone looks for it), `From` is the `.into()` conversion / generic
  `impl Into<...>`. Two different roles, 3 lines. Both coexist when `new`'s argument is the
  canonical content of the struct (e.g. `Vec<Attribute>`); provide only `new` if
  `From` has no semantic meaning.

- Cite the `file:line` read during this invocation. Two-part verdict: **proven**
  (command + output) / **not proven** (and why).
