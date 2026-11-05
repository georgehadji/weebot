# ruff: noqa: E501  (the parametrised cases are one-line source strings)
"""The complexity ratchet measures what it says (Q1)."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "lint_complexity.py"


@pytest.fixture(scope="module")
def lint():
    spec = importlib.util.spec_from_file_location("lint_complexity_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _function(source: str) -> ast.AST:
    return ast.parse(source).body[0]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f():\n    return 1\n", 1),
        ("def f(a):\n    if a:\n        return 1\n    return 2\n", 2),
        ("def f(a):\n    if a:\n        return 1\n    elif a is None:\n        return 2\n    return 3\n", 3),
        ("def f(a, b, c):\n    return a and b and c\n", 3),
        ("def f(a):\n    for x in a:\n        while x:\n            x -= 1\n", 3),
        ("def f(a):\n    try:\n        pass\n    except A:\n        pass\n    except B:\n        pass\n", 3),
        ("def f(a):\n    return [x for x in a if x if x > 1]\n", 4),
        ("def f(a):\n    return 1 if a else 2\n", 2),
        ("def f(a):\n    match a:\n        case 1:\n            pass\n        case _:\n            pass\n", 3),
    ],
)
def test_cyclomatic_complexity(lint, source, expected):
    assert lint.cyclomatic(_function(source)) == expected


def test_a_nested_function_does_not_count_toward_its_parent(lint):
    source = "def f(a):\n    def g(b):\n        if b:\n            return 1\n    return g\n"

    assert lint.cyclomatic(_function(source)) == 1


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f():\n    return 1\n", 0),
        ("def f(a):\n    if a:\n        pass\n", 1),
        ("def f(a):\n    if a:\n        pass\n    elif a is None:\n        pass\n    else:\n        pass\n", 1),
        ("def f(a):\n    for x in a:\n        if x:\n            with x:\n                pass\n", 3),
        ("def f(a):\n    try:\n        pass\n    except A:\n        pass\n    finally:\n        pass\n", 1),
        ("def f(a):\n    if a:\n        def g(b):\n            if b:\n                if b:\n                    pass\n", 1),
    ],
)
def test_nesting_depth(lint, source, expected):
    assert lint.nesting(_function(source)) == expected


def test_the_repository_is_at_both_ceilings():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stdout + result.stderr
