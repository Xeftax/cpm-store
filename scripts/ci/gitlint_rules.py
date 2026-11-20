"""Custom gitlint rules for cpm-store.

Loaded by gitlint via `extra-path` in .gitlint. One rule: a commit body must not
declare a pre-commit hook bypass (`--no-verify`, `Hooks-Bypassed`). Mirrors the
intent of scripts/ci/check-commit-hygiene.sh (branch review/pr8-remaining): git
does not record whether hooks ran, so a bypass must never be normalized in a
body — an exceptionally authorized bypass is a review-blocking finding, not a
line of metadata to copy.
"""

from gitlint.rules import CommitRule, RuleViolation

_BYPASS_MARKERS = ("--no-verify", "Hooks-Bypassed")


class BodyNoHookBypass(CommitRule):
    """Forbid hook-bypass markers anywhere in the commit body."""

    id = "UCP1"
    name = "body-no-hook-bypass"

    def validate(self, commit: object) -> list[RuleViolation]:
        """Return one violation per body line carrying a bypass marker."""
        violations: list[RuleViolation] = []
        message = commit.message  # type: ignore[attr-defined] # gitlint commit is Any
        for i, line in enumerate(message.body):
            if any(marker in line for marker in _BYPASS_MARKERS):
                msg = 'Body must not contain "--no-verify" or "Hooks-Bypassed"'
                violations.append(RuleViolation(self.id, msg, line, i + 1))
        return violations
