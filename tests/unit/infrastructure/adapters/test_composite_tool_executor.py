"""Unit tests for CompositeToolExecutor."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import pytest

from weebot.domain.models.composite_tool import CompositeToolSpec, SubToolCall
from weebot.infrastructure.adapters.composite_tool_executor import (
    CompositeToolExecutor,
)


class _FakeResult:
    """ToolResult-like stub."""

    def __init__(self, output: str = "", error: str | None = None) -> None:
        self.output = output
        self.error = error
        self.is_error = error is not None


def _make_dispatcher(
    steps: dict[str, list[str]],
) -> dict[str, Callable[..., Awaitable[Any]]]:
    """Build a dispatcher where each tool pops its next output from *steps*."""
    state = {name: list(outputs) for name, outputs in steps.items()}

    async def handler(tool_name: str, **kwargs):
        if not state.get(tool_name):
            return _FakeResult(error=f"no more outputs for {tool_name}")
        output = state[tool_name].pop(0)
        if output.startswith("ERROR:"):
            return _FakeResult(error=output[6:])
        return _FakeResult(output=output)

    return {
        name: lambda _name=name, **kwargs: handler(_name, **kwargs)
        for name in steps
    }


class TestCompositeToolExecutor:
    """Composite workflow execution."""

    @pytest.mark.asyncio
    async def test_runs_all_steps(self):
        spec = CompositeToolSpec(
            name="demo",
            description="Demo",
            sub_tools=[
                SubToolCall(tool_name="a", arguments={}),
                SubToolCall(tool_name="b", arguments={}),
            ],
        )
        dispatcher = _make_dispatcher({"a": ["alpha"], "b": ["beta"]})
        executor = CompositeToolExecutor(dispatcher)

        result = await executor.execute(spec)

        assert result.success is True
        assert "a" in result.summary
        assert "b" in result.summary
        assert len(result.sub_results) == 2

    @pytest.mark.asyncio
    async def test_captures_output_for_downstream_steps(self):
        spec = CompositeToolSpec(
            name="demo",
            description="Demo",
            sub_tools=[
                SubToolCall(
                    tool_name="search",
                    arguments={"query": "weather"},
                    capture_output_as="results",
                ),
                SubToolCall(
                    tool_name="summarize",
                    arguments={"text": "${results}"},
                ),
            ],
        )
        dispatcher = _make_dispatcher({
            "search": ["sunny"],
            "summarize": ["summary: sunny"],
        })
        executor = CompositeToolExecutor(dispatcher)

        result = await executor.execute(spec)

        assert result.success is True
        assert result.sub_results[1]["output"] == "summary: sunny"

    @pytest.mark.asyncio
    async def test_all_or_none_aborts_on_failure(self):
        spec = CompositeToolSpec(
            name="demo",
            description="Demo",
            sub_tools=[
                SubToolCall(tool_name="a", arguments={}),
                SubToolCall(tool_name="b", arguments={}),
            ],
            transaction_policy="all_or_none",
        )
        dispatcher = _make_dispatcher({"a": ["ok"], "b": ["ERROR:boom"]})
        executor = CompositeToolExecutor(dispatcher)

        result = await executor.execute(spec)

        assert result.success is False
        assert result.aborted_after_failure is True
        assert "b failed" in result.summary

    @pytest.mark.asyncio
    async def test_best_effort_continues_on_failure(self):
        spec = CompositeToolSpec(
            name="demo",
            description="Demo",
            sub_tools=[
                SubToolCall(tool_name="a", arguments={}),
                SubToolCall(tool_name="b", arguments={}),
            ],
            transaction_policy="best_effort",
        )
        dispatcher = _make_dispatcher({"a": ["ERROR:oops"], "b": ["ok"]})
        executor = CompositeToolExecutor(dispatcher)

        result = await executor.execute(spec)

        assert result.success is False  # because not all steps succeeded
        assert result.aborted_after_failure is False
        assert len(result.sub_results) == 2

    @pytest.mark.asyncio
    async def test_missing_tool_returns_error(self):
        spec = CompositeToolSpec(
            name="demo",
            description="Demo",
            sub_tools=[
                SubToolCall(tool_name="missing", arguments={}),
            ],
        )
        executor = CompositeToolExecutor({})

        result = await executor.execute(spec)

        assert result.success is False
        assert "missing" in result.summary

    @pytest.mark.asyncio
    async def test_runtime_args_override_template_args(self):
        spec = CompositeToolSpec(
            name="demo",
            description="Demo",
            sub_tools=[
                SubToolCall(tool_name="edit", arguments={"path": "default.txt"}),
            ],
        )

        captured: dict[str, str] = {}

        async def edit(path: str) -> _FakeResult:
            captured["path"] = path
            return _FakeResult(output="ok")

        executor = CompositeToolExecutor({"edit": edit})
        result = await executor.execute(spec, runtime_args={"path": "override.txt"})

        assert result.success is True
        assert captured["path"] == "override.txt"

    @pytest.mark.asyncio
    async def test_in_string_variable_substitution(self):
        spec = CompositeToolSpec(
            name="demo",
            description="Demo",
            sub_tools=[
                SubToolCall(
                    tool_name="read",
                    arguments={},
                    capture_output_as="content",
                ),
                SubToolCall(
                    tool_name="write",
                    arguments={"code": "print('${content}')"},
                ),
            ],
        )

        async def read() -> _FakeResult:
            return _FakeResult(output="hello")

        captured: dict[str, str] = {}

        async def write(code: str) -> _FakeResult:
            captured["code"] = code
            return _FakeResult(output="ok")

        executor = CompositeToolExecutor({"read": read, "write": write})
        result = await executor.execute(spec)

        assert result.success is True
        assert captured["code"] == "print('hello')"
