"""F04 and F05: ExecApprovalPolicy rule ordering (fixed in W3.3).

F04: the chained-command override returned "ask" before DENY rules were read,
so a chained Format-Volume was asked about instead of denied.
F05: Copy-Item, Move-Item, Rename-Item and plain Set-Content had no standalone
rule, so on their own they auto-approved.

The policy now splits a command into segments and folds them, DENY > ASK >
AUTO_APPROVE; the property tests pin that precedence for any mix of segments.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from weebot.core.approval_policy import ExecApprovalPolicy, split_segments

_POLICY = ExecApprovalPolicy()

# Commands with a known single-segment verdict and no separator or quote.
_ALLOW = ["Get-ChildItem C:\\", "echo hello", "git status"]
_ASK = ["Remove-Item old_logs", "reg delete HKCU\\X", "Copy-Item a.txt b.txt"]
_DENY = ["Format-Volume -DriveLetter D", "format C:"]
_ATOMS = _ALLOW + _ASK + _DENY
_SEPARATORS = ["; ", " && ", " || ", " | ", " & "]


def _rank(result) -> int:
    if not result.approved:
        return 2
    return 1 if result.requires_confirmation else 0


def test_chained_format_volume_is_denied():
    result = _POLICY.evaluate("Format-Volume -DriveLetter D; rm x")
    assert result.approved is False


def test_unchained_format_volume_is_denied():
    result = _POLICY.evaluate("Format-Volume -DriveLetter D")
    assert result.approved is False


@pytest.mark.parametrize(
    "command",
    [
        "Copy-Item C:\\a.txt C:\\b.txt",
        "Move-Item C:\\a.txt C:\\b.txt",
        "Rename-Item C:\\a.txt b.txt",
        "Set-Content C:\\a.txt hello",
    ],
)
def test_destructive_verb_alone_asks(command):
    assert _POLICY.evaluate(command).requires_confirmation is True


def test_output_carve_out_covers_only_its_own_segment():
    allowed = _POLICY.evaluate("Remove-Item C:\\x\\Output\\a")
    chained = _POLICY.evaluate("Remove-Item C:\\x\\Output\\a; Format-Volume -DriveLetter C")
    assert (_rank(allowed), _rank(chained)) == (0, 2)


@given(st.lists(st.sampled_from(_ATOMS), min_size=1, max_size=6), st.data())
def test_chain_verdict_is_the_strictest_segment(atoms, data):
    seps = [data.draw(st.sampled_from(_SEPARATORS)) for _ in atoms[1:]]
    command = atoms[0] + "".join(s + a for s, a in zip(seps, atoms[1:], strict=True))
    expected = max(_rank(_POLICY.evaluate(a)) for a in atoms)
    assert _rank(_POLICY.evaluate(command)) == expected


@given(st.lists(st.sampled_from(_ATOMS), min_size=1, max_size=6))
def test_any_deny_segment_denies(atoms):
    command = "; ".join(atoms + [_DENY[0]])
    assert _POLICY.evaluate(command).approved is False


@given(st.lists(st.sampled_from(_ATOMS), min_size=1, max_size=6))
def test_split_returns_the_segments(atoms):
    assert split_segments(" ; ".join(atoms)) == atoms


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ('echo "a; b" | sort', ['echo "a; b"', "sort"]),
        ("echo 'x && y'", ["echo 'x && y'"]),
        ("a&&b||c", ["a", "b", "c"]),
        ("", []),
    ],
)
def test_split_respects_quotes(command, expected):
    assert split_segments(command) == expected
