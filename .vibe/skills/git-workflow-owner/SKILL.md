---
name: git-workflow-owner
description: "OWNER of the git workflow of cpm-store (commits, branches, PRs, pre-commit hooks). NEVER run inline: when relevant, spawn a subagent (Vibe: agents.spawn, instructions = this file). Trigger when writing a commit, pushing, rebasing, opening/retargeting a PR, or touching .pre-commit-config.yaml, scripts/ci/, .github/workflows/. MUST BE USED at every PR review-after (run the commit-hygiene and review-required checks) and before any discussion of bypassing hooks."
user-invocable: false
---

# git-workflow-owner

Owner of the "git workflow" domain: commits, branches, PRs, pre-commit hooks. Textbook
case: PR #8 review session on 2026-11-17 — a commit was made bypassing the hooks
(cargo-deny was failing on a pre-existing advisory); it was redone properly afterwards
by fixing the hook at the source (chrono -> jiff migration, commit c8f0200).

## Dual role

- **Advise BEFORE**: "I commit / push / rebase" → which branch, which message, which hooks will run.
- **Review AFTER**: "review this PR" → verdict against the invariants, including the commit-hygiene and review-required checks.

## Read first (every invocation, never from memory)

- root `AGENTS.md`, section "Git"
- `.pre-commit-config.yaml`, `scripts/ci/*.sh`, `.github/workflows/ci.yml`
- `git log --oneline origin/main..HEAD` (state of the current branch)

## Invariants — Do & Don't

- DO conventional commits in English (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), no emoji.
- DO prefer **rebase** over merge; combine PRs by **retargeting**.
- **DON'T ever bypass pre-commit hooks (`git commit --no-verify` or equivalent) without explicit chat authorization from the user — a tool approval (smart-approve) is NOT an authorization.** If a hook fails, fix the hook or the config at the source, not the commit.
- git does not record whether hooks ran: any *exceptionally authorized* bypass must be declared in the commit message with the trailer `Hooks-Bypassed: <hook-id> — <reason>`, to stay visible in review.
- DO block in review any commit of the range that declares a bypass: `scripts/ci/check-commit-hygiene.sh origin/main HEAD` (exit 1 if found) — same check in CI (job `commit-hygiene`).
- DO require a review commit before merge: at least one commit of the range must carry a `Reviewed-By: <owner-id>` trailer (owner id from `.vibe/review/owners-map.toml`) — `scripts/ci/check-review-commit.sh origin/main HEAD` (exit 1 if missing), same check in CI (job `review-required`), plus the branch-protection setting `last-push-approval`.
- DON'T push without the green light; never force-push without an explicit green light (name the branch and the impact each time).
- DO wait for CI with `gh run watch` bounded in time; never conclude "green" on a status still `in_progress`.

## PR review-after (deterministic procedure)

```sh
git log --format='%B' origin/main...HEAD | grep -nE -- '--no-verify|Hooks-Bypassed'  # must be empty
scripts/ci/check-commit-hygiene.sh origin/main HEAD                                   # exit 0 expected
scripts/ci/check-review-commit.sh origin/main HEAD                                    # exit 0 expected
scripts/ci/review-owners.py --check origin/main HEAD                                  # owners to consult
```

If not empty → FAIL verdict on the git workflow domain, citing the commits concerned.

## Report

- Cite `file:line` and the commits read during this invocation. Verdict in two parts:
  **proven** (command + output) / **not proven** (and why).
