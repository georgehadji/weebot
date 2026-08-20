"""Tests for the restricted migration-script evaluator."""

from __future__ import annotations

import pytest

from weebot.templates.migration_eval import evaluate_migration_script


def test_simple_assignment() -> None:
    parameters = {"y": 1}
    result = {}
    evaluate_migration_script('result["x"] = parameters["y"]', parameters, result)
    assert result["x"] == 1


def test_string_method() -> None:
    parameters = {"name": "alice"}
    result = {}
    evaluate_migration_script('result["greet"] = parameters["name"].upper()', parameters, result)
    assert result["greet"] == "ALICE"


def test_len_function() -> None:
    parameters = {"items": [1, 2, 3]}
    result = {}
    evaluate_migration_script('result["count"] = len(parameters["items"])', parameters, result)
    assert result["count"] == 3


def test_get_method() -> None:
    parameters = {}
    result = {}
    evaluate_migration_script(
        'result["val"] = parameters.get("key", "default")', parameters, result
    )
    assert result["val"] == "default"


def test_import_rejected() -> None:
    with pytest.raises(ValueError, match="Import statements are not allowed"):
        evaluate_migration_script("import os", {}, {})


def test_eval_rejected() -> None:
    with pytest.raises(ValueError, match="Function call 'eval' is not allowed"):
        evaluate_migration_script('eval("1+1")', {}, {})


def test_dunder_rejected() -> None:
    with pytest.raises(ValueError, match="Dunder access"):
        evaluate_migration_script('"".__class__.__mro__', {}, {})


def test_arbitrary_function_rejected() -> None:
    with pytest.raises(ValueError, match="Function call 'open' is not allowed"):
        evaluate_migration_script('open("file.txt")', {}, {})


def test_arbitrary_attribute_rejected() -> None:
    with pytest.raises(ValueError, match="Dunder access"):
        evaluate_migration_script("parameters.__dict__", {}, {})


def test_unknown_name_rejected() -> None:
    with pytest.raises(
        ValueError, match="Assignments must be to result\\[...\\] or parameters\\[...\\]"
    ):
        evaluate_migration_script("unknown_var = 1", {}, {})
