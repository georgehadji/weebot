"""The patch matching chain finds the one place an edit belongs, or refuses (H6)."""

from __future__ import annotations

import pytest

from weebot.application.services.patch_matching import (
    STRATEGIES,
    BlockAnchor,
    EscapeNormalized,
    Exact,
    IndentationFlexible,
    LineTrimmed,
    UnicodeNormalized,
    WhitespaceNormalized,
    apply_patch,
)

CODE = "def f(a):\n    x = a + 1\n    return x\n\n\ndef g():\n    return 2\n"


def _slice(strategy, haystack, needle):
    return [haystack[s.start : s.end] for s in strategy.find(haystack, needle)]


@pytest.mark.parametrize(
    ("strategy", "needle", "expected"),
    [
        (Exact(), "x = a + 1", ["x = a + 1"]),
        (Exact(), "return", ["return", "return"]),
        (Exact(), "missing", []),
        (LineTrimmed(), "x = a + 1\nreturn x", ["    x = a + 1\n    return x"]),
        (LineTrimmed(), "      x = a + 1  ", ["    x = a + 1"]),
        (WhitespaceNormalized(), "x   =  a +1", []),  # "+1" has no space in the file: not equal
        (WhitespaceNormalized(), "x =   a  +  1", ["x = a + 1"]),
        (WhitespaceNormalized(), "def  f(a):\n  x = a + 1", ["def f(a):\n    x = a + 1"]),
        (IndentationFlexible(), "  x = a + 1\n  return x", ["    x = a + 1\n    return x"]),
        (IndentationFlexible(), "x = a + 1\nreturn x", ["    x = a + 1\n    return x"]),
        (EscapeNormalized(), "x = a + 1\\n    return x", ["x = a + 1\n    return x"]),
        (EscapeNormalized(), "no escapes here", []),
        (
            BlockAnchor(),
            "def f(a):\n    y = a + 1\n    return x",
            ["def f(a):\n    x = a + 1\n    return x"],
        ),
        (BlockAnchor(), "def f(a):\n    totally = different(stuff)\n    return x", []),
        (BlockAnchor(), "def f(a):\n    return x", []),  # fewer than three lines
    ],
)
def test_each_strategy_finds_its_span(strategy, needle, expected):
    assert _slice(strategy, CODE, needle) == expected


def test_unicode_normalized_matches_smart_quotes_and_dashes():
    text = "say \u201chello\u201d \u2013 it\u2019s fine\n"

    assert _slice(UnicodeNormalized(), text, "say \"hello\" - it's fine") == [text.rstrip("\n")]


def test_unicode_normalized_matches_compatibility_forms():
    assert _slice(UnicodeNormalized(), "an \ufb01nal word", "an final word") == ["an \ufb01nal word"]


def test_the_chain_runs_strictest_first():
    assert [s.name for s in STRATEGIES] == [
        "exact",
        "line_trimmed",
        "whitespace_normalized",
        "indentation_flexible",
        "escape_normalized",
        "unicode_normalized",
        "block_anchor",
    ]


def test_an_exact_match_reports_exact_and_its_line():
    out = apply_patch(CODE, "return 2", "return 3")

    assert out.ok and out.strategy == "exact" and out.line == 7
    assert out.text.endswith("return 3\n")


def test_several_exact_matches_are_refused_with_their_lines():
    out = apply_patch(CODE, "return", "yield")

    assert not out.ok
    assert "2 places" in out.error and "lines 3, 7" in out.error


def test_a_fuzzy_match_that_is_ambiguous_is_refused():
    text = "if a:\n    go()\nif b:\n    go()\n"

    out = apply_patch(text, "go()  ", "stop()")

    assert not out.ok and "line_trimmed" in out.error


def test_a_later_strategy_is_not_tried_after_one_matched():
    """Exact found two; a fuzzier strategy must not quietly pick one of them."""
    out = apply_patch("a b\na b\n", "a b", "x")

    assert not out.ok and "exact" in out.error


def test_no_match_names_the_closest_text():
    out = apply_patch(CODE, "def g(self):\n    return 2", "pass")

    assert not out.ok
    assert "not found" in out.error and "line 6" in out.error and "def g():" in out.error


def test_no_match_with_nothing_close_gives_no_snippet():
    out = apply_patch(CODE, "zzzzzzzzzzzzzzzz", "x")

    assert not out.ok and out.error == "old_str not found."


def test_an_empty_old_str_is_refused():
    assert not apply_patch(CODE, "", "x").ok


def test_exact_only_chain_does_not_fall_back():
    out = apply_patch(CODE, "x = a + 1\nreturn x", "pass", strategies=(Exact(),))

    assert not out.ok


def test_a_trimmed_match_is_reindented_to_the_file():
    out = apply_patch(CODE, "x = a + 1\nreturn x", "x = a + 2\nif x:\n    return x")

    assert out.ok and out.strategy == "line_trimmed"
    assert "    x = a + 2\n    if x:\n        return x\n" in out.text


def test_an_indentation_flexible_match_is_reindented_to_the_file():
    out = apply_patch(CODE, "  x = a + 1\n  return x", "  x = 0\n  return x")

    assert out.ok
    assert "    x = 0\n    return x\n" in out.text


def test_an_escape_match_unescapes_the_replacement_too():
    out = apply_patch("a = 1\nb = 2\n", "a = 1\\nb = 2", "a = 3\\nb = 4")

    assert out.ok and out.strategy == "escape_normalized"
    assert out.text == "a = 3\nb = 4\n"


def test_a_trailing_newline_in_old_and_new_does_not_double_up():
    out = apply_patch("one\n  two\nthree\n", "two\n", "TWO\n")

    assert out.ok and out.text == "one\n  TWO\nthree\n"


def test_whitespace_match_keeps_the_text_around_it():
    out = apply_patch("x = call(a,   b) + 1\n", "call(a, b)", "call(a)")

    assert out.ok and out.strategy == "whitespace_normalized"
    assert out.text == "x = call(a) + 1\n"
