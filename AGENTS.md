# AGENTS.md — cpm-store

Entry point for any agent (human or LLM) working on this repository.
Read this file **before any modification**, then `docs/architecture.md` and
`docs/specs.md`.

## Goal

Rust client library for the **OMA CPM** (Converged Personal Messaging) standard,
for **conversation backup / synchronization**. **Pilot use case: Linphone**
(SIP/RCS client) — the concrete case that drives decisions, tests and direction;
the library itself stays generic (C API reusable by any C/C++ client).

- V1 scope: CPM Message Storage via the RESTful API (OMA REST_NetAPI_NMS).
- Out of V1 scope: SIP/MSRP signaling, charging, interworking, IMAP binding
  (IMAP planned for a later phase, see `docs/roadmap.md`).

## Language and style

- **All repository content is English**: code, identifiers, comments (`///` and
  `//`), doc comments, `docs/`, README, this file, commit messages, PR titles and
  descriptions, CI scripts and their comments. No "the team is French-speaking"
  exception: this is an Apache-2.0 library meant for international integration
  (linphone-sdk), doc comments render in English on docs.rs, and grep/search only
  ever sees the source of truth. French is allowed only in chat responses to the
  maintainer (a user-level rule, not a repo rule).
- Enforcement is deterministic — `scripts/ci/check-language.py` scans the lines
  **added** by each change for French/accented characters, on every file type
  (`.rs`, `.md`, `.toml`, `.yml`, ...). It runs as the pre-commit hook `language`,
  as the blocking CI job `language (English-only added lines)`, as the Vibe hooks
  `language-pre-write` (message on every write that adds accented text) and
  `language-post-agent`. Excluded (generated/vendored): `**/Cargo.lock`,
  `docs/TREE.md`, `reports/**`. Pre-existing French lines are not flagged (added
  lines only); existing docs are translated as they are touched.
- **Closure parameters are always explicitly typed** (`|a: &&Attribute|`), even
  when the compiler infers them: PR diffs are read without IDE hover, and
  `Iterator::find` hands out double references that are easy to misread.
  Warning-level rule `closure-params-typed` in `tools/review-check`
  (contract documented in `.vibe/review/known-patterns.toml`).
- No emoji, direct and factual style.

## Commands

```sh
cargo build --workspace
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings   # zero warnings tolerated
cargo fmt --all -- --check
cargo doc --workspace --no-deps
```

CI (`.github/workflows/ci.yml`) replays exactly these commands.
MSRV: **1.85** (`rust-version` of the workspace), edition **2024**.

## Architecture and layering

See `docs/architecture.md`. Absolute rules:

```
cpm-ffi → cpm-client → { cpm-nms | cpm-imap (phase 7) } → cpm-core ports
                    └→ cpm-msg → cpm-core
```

**Ports & adapters** architecture (doc-station pattern):

- the **ports** = traits in `cpm-core::ports` (`StoreBackend`, `MessageStorage`,
  `SyncStateStore`); `cpm-core` is **pure**: no I/O, `#![forbid(unsafe_code)]`;
- the **adapters** = one crate per implementation (`cpm-nms` = REST, `cpm-imap` = IMAP);
- `Result<T, CpmError>` at every adapter boundary, no panic crosses it;
- `unsafe` is forbidden in the whole workspace **except** `cpm-ffi` (C FFI for
  liblinphone);
- Errors: `thiserror`. Never `unwrap`/`expect` outside tests.

## Tests and conformance

- Unit tests per module + integration tests with `wiremock` (mocked NMS server).
- "Golden" fixtures taken from the spec appendix examples (`docs/specs/`).
- Every SCR checked in `docs/conformance.md` must be covered by a test.

## Specifications

Read `docs/specs.md` before any implementation. Cite the **section number**
of the spec in code comments and commit messages when implementing a normative
procedure. Never invent a spec section: if a point is not covered by the spec,
note it explicitly in the PR.

## Git

- Prefer **rebase** over merge; combine PRs by **retargeting** rather than opening
  several.
- Conventional commits in English (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
  `chore:`).
- No emoji in commits.
- **Never bypass pre-commit hooks** (`git commit --no-verify` or equivalent) without
  **explicit chat authorization** from the user: a tool approval (smart-approve) is
  not an authorization. If a hook fails, fix the hook at the source, not the commit
  (e.g. 2026-11-17: cargo-deny blocked on RUSTSEC-2026-0543, chrono unmaintained,
  migration to jiff, commit c8f0200). Any exceptionally authorized bypass must be
  declared in the commit message (trailer `Hooks-Bypassed: <hook> — <reason>`):
  visible in review, blocked by the CI job `commit-hygiene`
  (`scripts/ci/check-commit-hygiene.sh`). Domain owner:
  `.vibe/skills/git-workflow-owner/SKILL.md`.
- **Review commit required before merge**: every PR must contain at least one
  commit carrying a `Reviewed-By: <owner-id>` trailer — typically an empty commit:
  `git commit --allow-empty -m "review: PR #N — <what was checked>" -m "Reviewed-By: <owner-id>"`.
  Enforced by the CI job `review-required` (`scripts/ci/check-review-commit.sh`,
  scans the PR range) plus the branch-protection setting `last-push-approval`
  ("require approval of the most recent reviewable push", declared in
  `dockyard.toml` `[platform]`). The owners to consult for a given diff are listed
  by `scripts/ci/review-owners.py` (map: `.vibe/review/owners-map.toml`), printed by
  the CI job `review-owners` and the Vibe hook `review-owners`.

## Working with an LLM on this repository

1. Read `AGENTS.md`, then `docs/architecture.md`, `docs/specs.md` and
   `docs/workflow.md` (development strategy, owner agents, human sync points).
2. Advance phase by phase (`docs/roadmap.md`) — do not skip a phase, do not start a
   phase before the previous one is green (tests + clippy).
3. Every PR covering an SCR updates `docs/conformance.md`.
4. Tests are mandatory with every behavior change.
5. Subagent delegation (Vibe): always spawn with a `config_name` — `explore-flash`
   (glm-flash, read-only) to read/explore code, `plan-exec` (glm-flash, write
   allowed) to execute a step-by-step plan. Never spawn a subagent without a
   `config_name` for delegated work. Before/after a PR touching a domain, spawn its
   owner skill (`.vibe/skills/*-owner`, instructions = the SKILL.md file); the owners
   triggered by the current diff are listed by `scripts/ci/review-owners.py`.
6. Language: any added line must be English — `scripts/ci/check-language.py`
   enforces it; closure parameters are always typed (rule `closure-params-typed`).

## Vibe / Mistral usage monitoring (100% monitored)

This project is fully tracked on the model-usage side: sessions, models, contexts,
tokens, costs. See `docs/monitoring.md`.

```sh
python3 tools/dashboard.py --project cpm                          # terminal snapshot
python3 tools/dashboard.py --project cpm --watch 5                # live (Ctrl-C)
python3 tools/dashboard.py --project cpm --html reports/dashboard.html --json reports/dashboard.json
python3 tools/usage_report.py --out-dir reports --project cpm     # aggregated report (tokens, cost)
```

- `tools/dashboard.py` reads `~/.vibe/logs/session` live (meta.json, journals
  `unified/*/journal/*.jsonl`, locks `active/`) + `config.toml` +
  `experiment_eval_cache.json`. It never reads `~/.vibe/.env`.
- `reports/` (dashboard.html/json, usage.json/md) is committed: it is the durable
  snapshot, independent of Vibe log retention.
- Do not delete Vibe sessions via `/resume` (press `d` twice) while monitoring is
  active: local logs have no automatic expiration.

## License

Apache-2.0 (`LICENSE`) — chosen for its GPLv3/AGPL compatibility, so the library
can be integrated into linphone-sdk.
