"""F3, F29, F19: the approval policy parses a shell word before it trusts it.

The policy reasoned about command text with regexes and string splits, while PowerShell
parses it differently, so each of these ran unasked (audit 2026-10-31):

* ``Output/a.txt,C:/Users/me/x.docx`` is one word to the policy and a two-item list to
  PowerShell; a backtick turns ``Output/.`./x`` into ``Output/../x``;
* ``cd`` counted as read-only, so the next segment was judged against this workspace's
  ``Output/`` while it ran in the new directory;
* ``$p += "..."`` is no ``=`` assignment, so ``$p`` looked assigned once;
* ``get-info.cmd`` was "read-only" for its ``get-`` prefix, and ``Get-ChildItem \\\\host\\share``
  opens an SMB connection;
* ``Invoke-Ex`pression`` evades every ``Invoke-Expression`` rule.

Every attack must come out "ask" or "deny", never auto-approved; the plain ``Output\\x``
writes the agent makes all day must stay silent.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from weebot.core.approval_policy import ExecApprovalPolicy, _in_output, is_read_only_segment
from weebot.core.bash_guard import BashGuard, RiskLevel
from weebot.core.shell_segments import ShellWord, has_dynamic_command_name, tokenize
from weebot.tools.bash_security import CommandRiskLevel, CommandSecurityAnalyzer

POLICY = ExecApprovalPolicy()


def _auto(command: str) -> bool:
    result = POLICY.evaluate(command)
    return result.approved and not result.requires_confirmation


# ── tokenize ────────────────────────────────────────────────────────────────


def test_tokenize_marks_what_powershell_would_expand():
    words = {w.text: w for w in tokenize('Set-Content Output/a.txt,b.txt "x y" $v a/*/b')}
    assert words["Output/a.txt,b.txt"].is_list
    assert words["$v"].has_variable
    assert words["a/*/b"].has_wildcard
    assert all(w.is_plain for w in tokenize(r"Set-Content Output\a.txt"))


def test_tokenize_marks_a_backtick_and_a_unc_path():
    assert tokenize("dir Output/.`./x")[1].has_escape
    assert tokenize(r"dir \\host\share\f")[1].is_unc


def test_tokenize_gives_nothing_for_an_unbalanced_quote():
    assert tokenize('Set-Content "Output/a.txt') == []


def test_a_shell_word_is_immutable():
    with pytest.raises(AttributeError):
        tokenize("dir x")[0].is_list = True  # type: ignore[misc]
    assert isinstance(tokenize("dir x")[0], ShellWord)


# ── F3: Output/ scope ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "Output/a.txt,C:/Users/me/x.docx",
        "Output/.`./x.docx",
        "Output/*/x.txt",
        "Output/a?/x.txt",
        "Output/[a].txt",
        "Output/$x",
        "Output/~x",
        "Output/a;b",
        r"\\host\share\Output\x",
    ],
)
def test_in_output_refuses_a_word_powershell_would_read_differently(path):
    assert not _in_output(path)


@pytest.mark.parametrize(
    "path",
    ["Output/a.txt", r"Output\sub\a.txt", "./Output/a.txt", "Output/tmp/*.tmp", "Output/a?.txt"],
)
def test_in_output_still_accepts_a_plain_output_path(path):
    """A `*` in the last part only picks files, so a cleanup like `tmp/*.tmp` stays silent."""
    assert _in_output(path)


@settings(max_examples=80, deadline=None)
@given(
    st.text(alphabet="abc/._-", max_size=8),
    st.sampled_from([",", "`", ";", "$", "~", "[", "]"]),
    st.text(alphabet="abc/._-", max_size=8),
)
def test_in_output_is_false_for_any_word_with_a_special_character(head, mark, tail):
    assert not _in_output(f"Output/{head}{mark}{tail}")


@settings(max_examples=40, deadline=None)
@given(st.sampled_from(["*", "?"]), st.text(alphabet="abc._-", min_size=1, max_size=6))
def test_in_output_is_false_for_a_wildcard_in_a_directory_part(mark, rest):
    assert not _in_output(f"Output/{mark}/{rest}")


@pytest.mark.parametrize(
    "command",
    [
        'Set-Content Output/a.txt,C:/Users/me/x.docx "x"',
        "Remove-Item Output/a.txt,C:/Users/me/x.docx",
        "Remove-Item Output/.`./x.docx",
        r"cd C:\Users\me\Documents; Remove-Item Output\x.docx -Force",
        r"Set-Location C:\Users\me; Remove-Item Output\x.docx",
        r"Push-Location C:\Users\me; Remove-Item Output\x.docx",
        r'$p = "Output\x"; $p += "\..\..\y"; Remove-Item $p',
        r'$p = "Output\x"; if ($true) { $p = "C:\Users\me\y" }; Remove-Item $p',
        r'$p = "Output\x"; Set-Variable p "C:\Users\me\y"; Remove-Item $p',
    ],
)
def test_the_attack_strings_are_never_auto_approved(command):
    assert not _auto(command), command


@pytest.mark.parametrize(
    "command",
    [
        r"Remove-Item Output\x.txt",
        r'Set-Content Output\x.txt "hi"',
        'Set-Content Output/sub/a.txt "x"',
        r'$d = "Output\x"; Set-Content "$d\a.txt" "hi"',
        r"Remove-Item Output\a.txt; Remove-Item Output\b.txt",
    ],
)
def test_a_plain_output_write_is_still_silent(command):
    assert _auto(command), command


# ── F19: read-only is an exact set ──────────────────────────────────────────


@pytest.mark.parametrize(
    "segment",
    [
        "get-info.cmd",
        "Get-Evil",
        "select-evil x",
        "Get-Credential",
        r"Get-ChildItem \\host\share",
        r"Get-Content \\host\share\f",
        "Get-Content //host/share/f",
        r".\run.ps1",
        r"C:\tools\dir.exe",
        "dir.exe x",
        "& dir",
    ],
)
def test_these_are_not_read_only(segment):
    assert not is_read_only_segment(segment), segment


@pytest.mark.parametrize(
    "segment",
    ["ls", "dir", "Get-ChildItem .", "Get-Content a.txt", "Select-String x a.txt", "git status"],
)
def test_the_plain_reads_still_are(segment):
    assert is_read_only_segment(segment), segment


# ── F29: an escaped or built command name ───────────────────────────────────

ESCAPED = ['Invoke-Ex`pression "x"', 'In`voke-Expression "x"', 'i`ex "x"']


@pytest.mark.parametrize("command", ESCAPED)
def test_a_backtick_in_a_command_name_does_not_hide_invoke_expression(command):
    assert not POLICY.evaluate(command).approved
    assert BashGuard().evaluate(command)[0] in (RiskLevel.DANGEROUS, RiskLevel.BLOCKED)
    assert CommandSecurityAnalyzer().analyze(command).risk_level is CommandRiskLevel.DANGEROUS


@pytest.mark.parametrize(
    "command",
    [
        '& ("Invoke-" + "Expression") "x"',
        '&("iex") "x"',
        '. ("I" + "EX") "x"',
        "& $cmd x",
        "dir; & ($a + $b) x",
    ],
)
def test_a_built_command_name_asks(command):
    assert has_dynamic_command_name(command)
    assert not _auto(command)
    assert CommandSecurityAnalyzer().analyze(command).risk_level is not CommandRiskLevel.SAFE


@pytest.mark.parametrize("command", ["dir", "cmd1 && cmd2", "echo a & echo b", "ls . x"])
def test_an_ordinary_command_is_not_a_dynamic_name(command):
    assert not has_dynamic_command_name(command)


def test_a_line_continuation_backtick_is_not_stripped_into_the_next_line():
    """A backtick before a newline joins lines; it must not glue words together."""
    command = "dir `\nInvoke-Expression x"
    assert not POLICY.evaluate(command).approved
