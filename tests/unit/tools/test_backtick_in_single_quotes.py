"""Backticks inside single quotes are text, not command substitution.

Seen in the 2026-10-23 agent-uses batch: writing markdown with inline code
(`README.md` and `VERSION`) through the shell was DENIED as "nested backtick
injection". Inside single quotes a backtick is literal in both bash and
PowerShell, so the rule now ignores single-quoted text. Double-quoted
backticks stay denied: in bash (use_wsl) they are command substitution.
"""

from __future__ import annotations

import pytest

from weebot.tools.bash_security import CommandRiskLevel, CommandSecurityAnalyzer

_A = CommandSecurityAnalyzer()


def test_markdown_in_single_quotes_is_not_injection():
    cmd = "Set-Content -Path Output/x.md -Value 'See `README.md` and `VERSION` for details'"
    assert _A.analyze(cmd).risk_level != CommandRiskLevel.DANGEROUS


@pytest.mark.parametrize(
    "cmd",
    [
        "echo `whoami` `id -u`",
        'Set-Content -Path x.md -Value "See `README.md` and `VERSION`"',
        "echo 'quoted' `whoami` `id -u`",  # substitution outside the quotes
    ],
)
def test_backticks_outside_single_quotes_are_still_denied(cmd):
    assert _A.analyze(cmd).risk_level == CommandRiskLevel.DANGEROUS
