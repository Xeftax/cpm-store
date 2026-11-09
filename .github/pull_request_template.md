<!-- Keep the Closes line: it links the PR to its issue so the board auto-tracks status
     and the issue auto-closes on merge. Use "Closes #N" / "Fixes #N" — a bare "(#N)"
     mention does NOT close; "Refs #N" is accepted too. The pr-issue-link check
     warns and never fails when the line is missing.
     Code PR with genuinely no issue? Apply the `no-issue` label to silence it. -->

Closes #

## What

## Notes / deviations from the ticket

## Test plan

- [ ] `uv run pytest -v`
- [ ] `uv run ruff check .`
- [ ] `uv run mypy . --config-file mypy.toml`
