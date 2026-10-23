"""The Output/ carve-out covers the file cmdlets the agent really uses there.

The W3.7 observe batch (2026-10-23) logged 7 guard ASKs in 28 runs, all on a
file the run itself had just written under Output/: Set-Content 5, Move-Item 1,
Remove-Item 1. The carve-out matched only Remove-Item with an absolute drive
path, so relative `Output/...` paths and the other cmdlets fell through to the
blanket ASK rules. Under enforce every one of those is a prompt a human
answers yes to.

Widened, but fail closed: every path argument must sit under the workspace's
Output/ folder, with no `..` and no `$` variable, and nothing else changes.
"""

from __future__ import annotations

import os

import pytest

from weebot.core.approval_policy import ApprovalMode, CommandRule, ExecApprovalPolicy

_POLICY = ExecApprovalPolicy()
_ROOT = os.getcwd()


def _asks(command: str) -> bool:
    result = _POLICY.evaluate(command)
    return (not result.approved) or result.requires_confirmation


@pytest.mark.parametrize(
    "command",
    [
        'Set-Content -Path "Output/observe/notes.txt" -Value "v2"',
        "Set-Content Output\\observe\\notes.txt 'v1'",
        "Add-Content -Path Output/observe/log.txt -Value line",
        "Remove-Item Output/observe/tmp/*.tmp",
        "Remove-Item -Path ./Output/observe/tmp -Recurse -Force",
        "Move-Item Output/observe/a/x.txt Output/observe/b/x.txt",
        "Copy-Item -Path Output/observe/a.txt -Destination Output/observe/b.txt -Force",
        "New-Item -ItemType Directory -Path Output/observe/a -Force",
        "Rename-Item Output/observe/a.txt b.txt",
        f"Remove-Item '{_ROOT}\\Output\\observe\\x.txt'",
    ],
)
def test_file_cmdlets_inside_output_are_auto_approved(command):
    assert not _asks(command), command


@pytest.mark.parametrize(
    "command",
    [
        "Set-Content README.md 'x'",  # a workspace file, not Output/
        "Move-Item README.md Output/x.md",  # moves a file out of its home
        "Copy-Item .env Output/env.txt",  # copies a secret into Output/
        "Remove-Item Output/../.env",  # traversal
        "Remove-Item Output",  # the whole folder
        "Set-Content -Path $p -Value x",  # a variable can hold any path
        "Remove-Item C:\\Windows\\Output\\x.txt",  # not this workspace's Output
        "Rename-Item Output/a.txt ../b.txt",  # renames out of Output/
        "Remove-Item Output/x.txt -Credential admin",  # unknown parameter
        "Set-Content Output/x.txt 'a'; Remove-Item README.md",  # chained
    ],
)
def test_anything_outside_output_still_asks(command):
    assert _asks(command), command


def test_a_user_rule_is_not_overridden_by_the_carve_out():
    policy = ExecApprovalPolicy(
        rules=[CommandRule(r"\bset-content\b", ApprovalMode.ALWAYS_ASK, is_regex=True)]
    )
    assert policy.evaluate("Set-Content Output/x.txt 'a'").requires_confirmation


def test_a_deny_still_wins_inside_output():
    assert not _POLICY.evaluate("Format-Volume -DriveLetter D; Remove-Item Output/x").approved


# The agent's real shape (traced in the observe rerun): a literal path in a
# variable, then chained cmdlets on it. A variable assigned exactly once to a
# plain string literal in the same command is substituted before judging.
_W = _ROOT


@pytest.mark.parametrize(
    "command",
    [
        rf'$dir = "{_W}\Output\observe\tmp"; New-Item -ItemType Directory -Force -Path $dir '
        r'| Out-Null; Set-Content -Path "$dir\a.tmp" -Value "temp a"; Remove-Item -Path '
        r'"$dir\*.tmp" -Force; $remaining = Get-ChildItem $dir; '
        r'if ($remaining.Count -eq 0) { Write-Output "EMPTY" }',
        rf'$base = "{_W}\Output\observe"; Set-Content -Path "$base\zipme\a.txt" -Value '
        r'"zip test" -NoNewline; Compress-Archive -Path "$base\zipme" -DestinationPath '
        r'"$base\zipme.zip" -Force',
        rf'$root = "{_W}\Output\observe"; Move-Item -Path "$root\a\x.txt" -Destination '
        r'"$root\b\x.txt" -Force; Write-Output ("Exists: " + (Test-Path "$root\b\x.txt"))',
    ],
)
def test_a_literal_path_variable_inside_output_is_followed(command):
    assert not _asks(command), command


@pytest.mark.parametrize(
    "command",
    [
        r'$d = "C:\Windows"; Remove-Item "$d\x.txt"',  # the literal is outside Output/
        r'$d = "Output/x"; $d = "C:\Windows"; Remove-Item $d',  # reassigned
        r'$d = Get-Location; Remove-Item "$d\Output\x"',  # not a literal
        r'$d = "Output/$env:USERNAME"; Remove-Item $d',  # literal holds a variable
    ],
)
def test_a_variable_that_is_not_a_single_safe_literal_still_asks(command):
    assert _asks(command), command


# Seen under enforce (2026-10-23): the delete sits in an existence guard.
@pytest.mark.parametrize(
    "command",
    [
        rf'$dst = "{_W}\Output\observe\zipme.zip"; '
        r"if (Test-Path $dst) { Remove-Item $dst -Force }; "
        r"Compress-Archive -Path Output/observe/zipme -DestinationPath $dst -Force",
        r"if(Test-Path Output/x.zip){Remove-Item Output/x.zip -Force}",
    ],
)
def test_an_existence_guarded_cmdlet_inside_output_is_auto_approved(command):
    assert not _asks(command), command


@pytest.mark.parametrize(
    "command",
    [
        r"if (Test-Path Output/x) { Remove-Item README.md }",  # body outside Output/
        r"if (Set-Content README.md x) { Remove-Item Output/x }",  # condition writes
        r"if (Test-Path Output/x) { Remove-Item Output/x; Remove-Item README.md }",  # two cmdlets
    ],
)
def test_a_guard_that_hides_anything_else_still_asks(command):
    assert _asks(command), command
