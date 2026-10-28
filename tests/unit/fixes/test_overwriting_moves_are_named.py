"""A move or copy that overwrites a file is asked about as an overwrite, and avoided.

Found on live session de5d0990 ("tidy up my Downloads, deletion is not permitted"): the
plan moved every file by extension and said nothing about two files with one name.
``Move-Item -Force`` replaces the file already at the destination, which is a
deletion. The approval prompt for it read "Note the source path so the move can be
reversed", which is not true of an overwrite; ``mv -f``, ``cp -f`` and ``move /Y`` were
not asked about at all.
"""

from __future__ import annotations

import pytest

from weebot.application.agents.executor._prompt_builder import _BOOT_BLOCK
from weebot.core.approval_policy import ExecApprovalPolicy


@pytest.mark.parametrize(
    "command",
    [
        r"Move-Item -Path C:\Users\me\Downloads\a.pdf -Destination C:\Users\me\Downloads\Documents -Force",
        r"Get-ChildItem *.jpg | Move-Item -Destination C:\Users\me\Pictures -Force",
        r"Copy-Item a.txt C:\Users\me\b.txt -Force",
        "mv -f a.txt b.txt",
        "cp -f a.txt b.txt",
        "move /Y a.txt b.txt",
    ],
)
def test_an_overwrite_is_asked_about_as_one(command):
    result = ExecApprovalPolicy().evaluate(command)
    assert result.requires_confirmation
    assert "overwrite" in result.undo_hint.lower()


def test_a_plain_move_keeps_its_hint():
    result = ExecApprovalPolicy().evaluate(r"Move-Item a.pdf C:\Users\me\Documents")
    assert result.requires_confirmation and "overwrite" not in result.undo_hint.lower()


def test_the_executor_is_told_to_keep_both_files():
    text = _BOOT_BLOCK.lower()
    assert "-force" in text and "overwrite" in text and "suffix" in text
