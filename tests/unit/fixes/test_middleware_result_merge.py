"""Middleware that rewrites a tool's output does not crash the executor (F64).

The executor rebuilt the result as `ToolResult(..., is_error=...)`, but
`is_error` is a property, not a field, so any rewrite raised `TypeError`.
It also dropped `data` and `metadata`.
"""

from __future__ import annotations

from types import SimpleNamespace

from weebot.application.agents.executor._base import _merge_middleware_result
from weebot.domain.models.tool_result import ToolResult


def test_a_rewritten_output_keeps_data_and_metadata():
    result = ToolResult(output="raw", data={"k": 1}, metadata={"m": 2})
    merged = _merge_middleware_result(
        result, SimpleNamespace(output="clean", error=None, is_error=False)
    )
    assert merged.output == "clean" and not merged.is_error
    assert merged.data == {"k": 1} and merged.metadata == {"m": 2}


def test_middleware_can_mark_an_error():
    merged = _merge_middleware_result(
        ToolResult(output="raw"), SimpleNamespace(output="blocked", error="nope", is_error=True)
    )
    assert merged.is_error and merged.error == "nope"
