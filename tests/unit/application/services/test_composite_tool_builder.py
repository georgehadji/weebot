"""Tests for CompositeToolBuilder."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult

from weebot.application.services.composite_tool_builder import CompositeToolBuilder
from weebot.domain.models.composite_tool import CompositeResult, CompositeToolSpec, SubToolCall


class _FakeResult:
    """Minimal result-like object for the builder's handler."""

    def __init__(self, success: bool, summary: str) -> None:
        self.success = success
        self.summary = summary


def _make_spec() -> CompositeToolSpec:
    """Return a composite spec with a mix of runtime and captured vars."""
    return CompositeToolSpec(
        name="analyze_and_edit",
        description="Analyze a file and edit it.",
        sub_tools=[
            SubToolCall(
                tool_name="file_view",
                arguments={"path": "${path}"},
                capture_output_as="file_content",
            ),
            SubToolCall(
                tool_name="python_execute", arguments={"code": "print('''${file_content}''')"}
            ),
            SubToolCall(
                tool_name="file_str_replace",
                arguments={"path": "${path}", "old_str": "${old_str}", "new_str": "${new_str}"},
            ),
        ],
    )


@pytest.mark.asyncio
async def test_handler_invokes_executor_with_runtime_args() -> None:
    """The built handler passes only runtime args to the executor."""
    spec = _make_spec()
    executor = AsyncMock(return_value=_FakeResult(success=True, summary="ok"))
    builder = CompositeToolBuilder()

    handler = builder.build(spec, executor)
    result = await handler(path="test.txt", old_str="old", new_str="new")

    executor.assert_awaited_once_with(
        spec, runtime_args={"path": "test.txt", "old_str": "old", "new_str": "new"}
    )
    assert isinstance(result, CallToolResult)
    assert not result.isError
    assert any("ok" in item.text for item in result.content)


def test_signature_contains_only_unbound_runtime_vars() -> None:
    """Captured output vars must not appear as handler parameters."""
    spec = _make_spec()
    builder = CompositeToolBuilder()

    handler = builder.build(spec, AsyncMock())
    params = list(inspect.signature(handler).parameters.keys())

    assert "path" in params
    assert "old_str" in params
    assert "new_str" in params
    assert "file_content" not in params


@pytest.mark.asyncio
async def test_handler_returns_error_on_failed_execution() -> None:
    """A failed composite result is returned as an MCP error."""
    spec = _make_spec()
    executor = AsyncMock(return_value=_FakeResult(success=False, summary="step failed"))
    builder = CompositeToolBuilder()

    handler = builder.build(spec, executor)
    result = await handler(path="test.txt")

    assert isinstance(result, CallToolResult)
    assert result.isError
    assert any("step failed" in item.text for item in result.content)


@pytest.mark.asyncio
async def test_handler_returns_error_when_executor_raises() -> None:
    """An exception from the executor is surfaced as an MCP error."""
    spec = _make_spec()
    executor = AsyncMock(side_effect=RuntimeError("executor exploded"))
    builder = CompositeToolBuilder()

    handler = builder.build(spec, executor)
    result = await handler(path="test.txt")

    assert isinstance(result, CallToolResult)
    assert result.isError
    assert any("executor exploded" in item.text for item in result.content)


def test_handler_metadata_reflects_spec() -> None:
    """Handler name, docstring, and signature are derived from the spec."""
    spec = _make_spec()
    builder = CompositeToolBuilder()

    handler = builder.build(spec, AsyncMock())

    assert handler.__name__ == spec.name
    assert handler.__doc__ == spec.description
    sig = inspect.signature(handler)
    for param in sig.parameters.values():
        assert param.kind == inspect.Parameter.KEYWORD_ONLY


@pytest.mark.asyncio
async def test_builder_accepts_real_composite_result() -> None:
    """The builder works with the actual CompositeResult model."""
    spec = CompositeToolSpec(
        name="noop",
        description="No-op composite.",
        sub_tools=[SubToolCall(tool_name="ping", arguments={})],
    )
    executor = AsyncMock(return_value=CompositeResult(success=True, summary="done", sub_results=[]))
    builder = CompositeToolBuilder()

    handler = builder.build(spec, executor)
    result = await handler()

    assert isinstance(result, CallToolResult)
    assert not result.isError
    assert any("done" in item.text for item in result.content)
