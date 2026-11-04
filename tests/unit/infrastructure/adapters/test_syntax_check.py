"""InProcessSyntaxCheck reports what a parser reports, by file extension (H6)."""

from __future__ import annotations

import pytest

from weebot.infrastructure.adapters.syntax_check import InProcessSyntaxCheck

CHECK = InProcessSyntaxCheck()


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("a.py", "x = 1\n"),
        ("a.json", '{"a": [1, 2]}'),
        ("a.ipynb", '{"cells": []}'),
        ("a.toml", "[t]\nk = 1\n"),
        ("a.yaml", "a:\n  - 1\n"),
        ("a.yml", "---\na: 1\n---\nb: 2\n"),
        ("a.md", "((( not checked"),
        ("noext", "((( not checked"),
        ("A.PY", "x = 1\n"),
    ],
)
def test_valid_or_unknown_text_has_no_problems(path, text):
    assert CHECK.check(path, text) == []


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        ("a.py", "def f(:\n    pass\n", "Python syntax error at line 1"),
        ("a.py", "x = (\n", "Python syntax error"),
        ("a.json", '{"a": 1,}', "JSON error"),
        ("a.ipynb", "not json", "JSON error"),
        ("a.toml", "k = \n", "TOML error"),
        ("a.yaml", "a: [1, 2\n", "YAML error"),
    ],
)
def test_broken_text_is_reported(path, text, expected):
    problems = CHECK.check(path, text)

    assert len(problems) == 1 and expected in problems[0]
