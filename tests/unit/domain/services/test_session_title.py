"""derive_session_title: a free, deterministic label from a prompt (UI/UX plan, Phase 2)."""

from __future__ import annotations

import pytest

from weebot.domain.services.session_title import derive_session_title


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", ""),
        ("   \n\t ", ""),
        (None, ""),
        ("Summarize the quarterly report", "Summarize the quarterly report"),
        ("  Fix   the   login\tbug  ", "Fix the login bug"),
        ("\n\nFirst real line\nsecond line", "First real line"),
        ("# Build a **dashboard** for `sales`", "Build a dashboard for sales"),
        ("3) Rename the module", "Rename the module"),
        ("See [the docs](https://example.com/x) first", "See the docs first"),
        ("Read https://example.com/a/b and summarise", "Read and summarise"),
        ("```python\nprint(1)\n```\nWhat does this do?", "print(1)"),
        ("Φτιάξε μια αναφορά πωλήσεων για τον Οκτώβριο", "Φτιάξε μια αναφορά πωλήσεων για τον Οκτώβριο"),
    ],
)
def test_cleans_and_picks_the_first_meaningful_line(text, expected):
    assert derive_session_title(text) == expected


def test_a_prompt_that_is_only_a_link_shows_the_link_without_its_scheme():
    assert derive_session_title("https://example.com/page") == "example.com/page"


def test_long_text_is_cut_at_a_word_boundary_with_an_ellipsis():
    text = "word " * 40
    title = derive_session_title(text, max_len=30)
    assert title.endswith("…")
    assert len(title) <= 30
    assert title.removesuffix("…").split(" ")[-1] == "word"


def test_an_unbroken_token_is_cut_hard_rather_than_discarded():
    title = derive_session_title("x" * 200, max_len=20)
    assert title == "x" * 19 + "…"


def test_exactly_max_len_is_returned_untouched():
    assert derive_session_title("a" * 60) == "a" * 60


def test_cutting_on_a_space_keeps_every_whole_word():
    assert derive_session_title("aaaa bbbb cccc", max_len=10) == "aaaa bbbb…"
