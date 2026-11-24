---
name: review-memory-owner
description: "OWNER of the cpm-store review memory (known-patterns: what to record, which severity, indexing of occurrences, hygiene of the mechanism). NEVER run inline: when relevant, spawn a subagent (Vibe: agents.spawn, instructions = this file). Trigger when adding/changing a rule in .vibe/review/known-patterns.toml or the check script, or when a review comment reveals a new anti-pattern. MUST BE USED before setting any severity above warning and before indexing occurrences."
user-invocable: false
---

# review-memory-owner

Owner of the "review memory" domain: turn past PR comments into executable rules
(known-patterns), without noise or false positives. Reference case: PR #3
(comments on `attribute.rs` lines 23/40/53 + recap) + council of 2026-11-14
(5 advisors + 5 peer-reviews + chairman).

## Dual role

- **Advise BEFORE**: "we found an anti-pattern" -> which rule, which severity, which occurrences to index.
- **Review AFTER**: verdict against the invariants.

## Read first (on every invocation, never from memory)

- `.vibe/review/known-patterns.toml` (when it exists) + `scripts/review/check-known-patterns.sh`
- The domain owner skills: `model-struct-owner`, `serde-mapping-owner`, `constructor-owner`
- `docs/planning/review-strategy.md` (doc-station) — the reference deterministic practice

## Invariants — Do & Don't

### what to record, and when

- DO record an anti-pattern **from the 1st occurrence** — nothing prevents it from recurring.
  ("Reported twice" threshold rejected: recurrence is not a prerequisite for documentation.)
- **NEVER DELETE A RULE.** If it no longer works: edit/adapt it (regex, scope),
  or exclude it per file via `exclude_files = [...]` in the pattern (equivalent of
  `#[allow(...)]` lints), or at worst escape hatch per line `// review: ignore <rule-id>`.
  A rule removed from the TOML loses its occurrence history.
- DO restrict the `scope` to a single file during a progressive review (e.g. attribute.rs
  first, kind.rs next) instead of scoping everything at once and drowning in false positives.
- **A file goes into `exclude_files` only with the user's explicit agreement.**
  By default keep the warnings: they disappear when the rule or the files are
  fixed, not by hiding them.
- **Detection is deterministic CODE, not a regex nor prose**: every rule is an
  AST function in `tools/review-check` (parse with `syn`, like a clippy lint), executed
  by the checker. The TOML (`known-patterns.toml`) only provides the config (id, scope,
  severity, exclude_files, message, occurrences) + the DOC (`rule`, `applies_to`,
  `when_not_applicable`, `bad_example`, `good_example`) for debugging and LLM reading —
  the doc never replaces the executable rule.
- **Start BROAD, tighten later.** The AST rule matches the principle (e.g. "any newtype
  with a pub field, whatever the inner", "any method `fn foo(&self) { self.x.foo(..) }"`),
  not one specific object. Tighten as examples come in via `when_not_applicable`.
- DO index **all occurrences** (file:line or commit of first appearance), not what
  replaced them: if the rule is changed/removed one day, we must be able to list in one shot
  all the affected parts of the code and verify that the rule change is justifiable
  everywhere, then adapt each place to the new rule.
- DON'T turn one-offs into gates (see severity).

### severity

- DO `severity = "warning"` for **every** style/design pattern.
- DON'T put a hard gate on a style pattern: the reviewer is an LLM that reads **all** the
  warnings (and can also run dedicated passes "look at all warnings / fix them all"),
  whereas a human would ignore the warnings. Forcing it blocks and slows with no gain.
- DO reserve **blocking for functional issues only**: compiler, tests, `clippy -D`.
  That is already covered elsewhere — do not duplicate it in known-patterns.

### hygiene of the mechanism

- DO run the check on the **PR diff**, not whole files (otherwise re-flagging already
  fixed patterns = noise).
- DO provide an escape hatch `// review: ignore <rule-id>` (otherwise the gate ends up
  bypassed in bulk -> silent false negative).
- DO sunset: a rule never hit in N reviews is archived, not blindly deleted.
- DO measure first: retrospective grep of the patterns over the **whole git history**
  (`git log -p --all | grep -E <pattern>`) before freezing anything — the metric of
  real recurrence. (Done for PR #3: `one_or_many` = 15 additions/9 files -> recurrent
  class; `struct Helper` = 2 -> one-off.)
- DON'T use embeddings/RAG at this stage (corpus too small -> noise). Residual LLM only if a
  semantic pattern is **proven missed twice** by the grep.
- DO run the check on the whole repo once to verify it does not shout at healthy code.

### format of known-patterns.toml

```toml
[[pattern]]
id = "serde-helper-identity"          # kebab-case, stable (referenced by review: ignore)
scope = "crates/**/*.rs"               # glob of the check
regex = "struct Helper"                # deterministic pattern (grep -E), no semantics
message = "manual Deserialize impl + Helper: if the conversion is an identity copy, put #[serde(...)] on the field — see serde-mapping-owner"
severity = "warning"                   # always warning (see invariants)
occurrences = [                        # ALL the occurrences, never the replacement
  { file = "crates/cpm-core/src/model/attribute.rs", lines = "26-37", since = "PR #3" },
]
```

## Report

- Cite the `file:line` read during this invocation. Two-part verdict: **proven**
  (command + output) / **not proven** (and why).
