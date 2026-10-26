"""H1.1: an empty command is SAFE *and says so*.

The round-2 audit ask was a contract question -- is `BashGuard` a content guard or a
precondition guard? -- recorded as candidate H1.1 and left open because the answer
decides what the empty case should return.

Decided 2026-10-25: a content guard. It has no verdict to give about absent content,
so it keeps returning SAFE (a command that cannot run cannot be destructive) but
attaches a named `<empty>` check, because `(SAFE, [])` -- "evaluated, nothing found" --
and `(SAFE, [])` -- "nothing to evaluate" -- were the same value. The caller that
expected a command could not tell an approval from an absence.

These tests hold both halves: the verdict stays SAFE, and the absence is visible.
"""

from __future__ import annotations

from weebot.core.bash_guard import BashGuard, RiskLevel


def _patterns(checks) -> set[str]:
    return {check.pattern for check in checks}


class TestAnEmptyCommandIsSafeButNamed:
    def test_an_empty_command_is_still_safe(self):
        """The decision, not an accident: it must not start blocking anything."""
        guard = BashGuard()
        assert guard.evaluate("")[0] is RiskLevel.SAFE
        assert guard.is_safe("") is True

    def test_whitespace_only_is_the_same_case(self):
        guard = BashGuard()
        for command in ("", " ", "   ", "\t", "\n", " \t\n "):
            risk, checks = guard.evaluate(command)
            assert risk is RiskLevel.SAFE, command
            assert "<empty>" in _patterns(checks), command

    def test_the_absence_is_visible_in_the_checks(self):
        """The point of the decision: `(SAFE, [])` no longer means two different things."""
        risk, checks = BashGuard().evaluate("")
        assert risk is RiskLevel.SAFE
        assert len(checks) == 1
        assert checks[0].pattern == "<empty>"
        assert checks[0].risk_level is RiskLevel.SAFE
        assert "nothing to evaluate" in checks[0].description

    def test_a_real_command_that_matches_nothing_does_not_carry_the_marker(self):
        """The distinction this exists for: safe-because-evaluated vs nothing-to-evaluate."""
        risk, checks = BashGuard().evaluate("echo hello")
        assert risk is RiskLevel.SAFE
        assert checks == []
        assert "<empty>" not in _patterns(checks)

    def test_a_dangerous_command_is_unaffected(self):
        risk, checks = BashGuard().evaluate("rm -rf /")
        assert risk is not RiskLevel.SAFE
        assert "<empty>" not in _patterns(checks)
