"""A forced move or copy is asked about whatever name the command goes by.

Found by review of the de5d0990 fixes: the overwrite rules matched ``-Force`` only after
``Move-Item``, ``Copy-Item`` or ``Rename-Item``. The PowerShell aliases (``mv``, ``move``,
``mi``, ``cp``, ``copy``, ``cpi``) with a trailing ``-Force`` matched no rule and were
approved without a prompt, and ``-Fo`` (PowerShell accepts any unique prefix) was asked
about as a plain move.
"""

from __future__ import annotations

import pytest

from weebot.core.approval_policy import ExecApprovalPolicy


@pytest.mark.parametrize(
    "command",
    [
        r"mv a.pdf C:\Users\me\Documents\a.pdf -Force",
        r"move a.pdf C:\Users\me\Documents -Force",
        r"mi a.pdf C:\Users\me\Documents -Force",
        r"cp a.txt C:\Users\me\b.txt -Force",
        r"copy a.txt C:\Users\me\b.txt -Force",
        r"cpi a.txt C:\Users\me\b.txt -Force",
        r"Move-Item a.pdf C:\Users\me\Documents -Fo",
        r"Move-Item a.pdf C:\Users\me\Documents -Force:$true",
    ],
)
def test_a_forced_alias_is_asked_about_as_an_overwrite(command):
    result = ExecApprovalPolicy().evaluate(command)
    assert result.requires_confirmation
    assert "overwrite" in result.undo_hint.lower()


def test_an_alias_word_inside_another_command_is_not_a_move():
    result = ExecApprovalPolicy().evaluate("Get-Content notes-copy.txt -Force")
    assert "overwrite" not in result.undo_hint.lower()
