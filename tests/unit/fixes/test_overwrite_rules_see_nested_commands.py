"""Copy and move rules see the command wherever it sits, and under any alias.

Found by review of the alias fix:
- anchoring the forced-move rule to the segment start missed a ``Move-Item -Force``
  inside a script block or parentheses, which then got the plain-move hint ("the move
  can be reversed") for a command that overwrites files;
- the aliases were added only to the forced rule, so ``copy a b`` (Copy-Item overwrites
  by default) and ``mv a b`` asked nothing while their full names asked.
"""

from __future__ import annotations

import pytest

from weebot.core.approval_policy import ExecApprovalPolicy


@pytest.mark.parametrize(
    "command",
    [
        r"Get-ChildItem *.txt | ForEach-Object { Move-Item $_ D:\out -Force }",
        r"ForEach-Object { mv $_ D:\out -Force }",
        r"(Copy-Item a.txt b.txt -Force)",
        r"if ($x) { Copy-Item a.txt b.txt -Force }",
        r'powershell -Command "Copy-Item a.txt b.txt -Force"',
        r"mv -f a.txt b.txt",
    ],
)
def test_a_nested_forced_move_is_an_overwrite(command):
    result = ExecApprovalPolicy().evaluate(command)
    assert result.requires_confirmation
    assert "cannot be recovered" in result.undo_hint


@pytest.mark.parametrize(
    "command",
    [
        "copy a.txt b.txt",
        "cp a.txt b.txt",
        "cpi a.txt b.txt",
        "mv a.txt b.txt",
        "move a.txt b.txt",
        "mi a.txt b.txt",
        r"ForEach-Object { cp $_ D:\out }",
    ],
)
def test_a_plain_alias_is_asked_like_its_cmdlet(command):
    assert ExecApprovalPolicy().evaluate(command).requires_confirmation


def test_an_alias_word_in_an_argument_is_not_a_command():
    assert not ExecApprovalPolicy().evaluate('git commit -m "copy fix"').requires_confirmation
