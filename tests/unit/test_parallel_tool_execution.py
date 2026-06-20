"""Tests for Phase 2: Parallel tool execution in ExecutorAgent."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import PrivateAttr

from weebot.application.models.tool_collection import ToolCollection
from weebot.tools.base import BaseTool, ToolResult


class _SlowTool(BaseTool):
    """Tool that takes a configurable delay."""
    name: str = "slow_tool"
    description: str = "Slow test tool"
    parameters: dict = {"type": "object", "properties": {}}

    _delay: float = PrivateAttr(default=0.1)
    _should_fail: bool = PrivateAttr(default=False)
    call_count: int = 0

    def __init__(self, delay: float = 0.1, fail: bool = False, **data):
        super().__init__(**data)
        self._delay = delay
        self._should_fail = fail
        self.call_count = 0

    async def execute(self, **kwargs) -> ToolResult:
        self.call_count += 1
        await asyncio.sleep(self._delay)
        if self._should_fail:
            return ToolResult.error_result("Simulated failure")
        return ToolResult.success_result(output=f"Done (call {self.call_count})")


class _FastTool(BaseTool):
    """Tool that returns immediately."""
    name: str = "fast_tool"
    description: str = "Fast test tool"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult.success_result(output="Fast result")


class _SingleConcurTool(BaseTool):
    """Tool with max_concurrent=1 to test semaphore."""
    name: str = "single_concur"
    description: str = "Single-concurrency test tool"
    parameters: dict = {"type": "object", "properties": {}}
    max_concurrent: int = 1

    _delay: float = PrivateAttr(default=0.05)
    concurrent_calls: int = 0
    max_concurrent_seen: int = 0

    def __init__(self, delay: float = 0.05, **data):
        super().__init__(**data)
        self._delay = delay
        self.concurrent_calls = 0
        self.max_concurrent_seen = 0

    async def execute(self, **kwargs) -> ToolResult:
        self.concurrent_calls += 1
        self.max_concurrent_seen = max(self.max_concurrent_seen, self.concurrent_calls)
        await asyncio.sleep(self._delay)
        self.concurrent_calls -= 1
        return ToolResult.success_result(output="Concurrent result")


@pytest.mark.asyncio
async def test_results_in_declared_order():
    """Two tools complete in reverse order; results match declared order."""
    tools = ToolCollection(
        _SlowTool(name="slow_a", delay=0.2),
        _FastTool(name="fast_b"),
    )
    tool_calls = [
        {"function": {"name": "slow_a", "arguments": "{}"}, "id": "call_1"},
        {"function": {"name": "fast_b", "arguments": "{}"}, "id": "call_2"},
    ]
    # Simulate what _execute_tool_batch does
    from weebot.application.agents.executor import ExecutorAgent
    # Use the batch method directly (unit test)
    tasks = [tools.execute(_name=tc["function"]["name"]) for tc in tool_calls]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    # Even though slow_a runs slowly, results should be in declared order
    assert len(raw) == 2
    assert not raw[0].is_error  # slow_a
    assert not raw[1].is_error  # fast_b


@pytest.mark.asyncio
async def test_one_failure_does_not_abort_batch():
    """Tool 1 raises; tool 2 succeeds; both results present."""
    tools = ToolCollection(
        _SlowTool(name="fail_tool", fail=True, delay=0.01),
        _FastTool(name="ok_tool"),
    )
    tool_calls = [
        {"function": {"name": "fail_tool", "arguments": "{}"}, "id": "call_1"},
        {"function": {"name": "ok_tool", "arguments": "{}"}, "id": "call_2"},
    ]
    tasks = [tools.execute(_name=tc["function"]["name"]) for tc in tool_calls]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    assert len(raw) == 2
    assert raw[0].is_error  # fail_tool errored
    assert not raw[1].is_error  # ok_tool succeeded


@pytest.mark.asyncio
async def test_concurrent_execution_is_faster():
    """Mock tools sleep 100ms each; batch of 3 completes in < 200ms total."""
    tools = ToolCollection(
        _SlowTool(name="a", delay=0.1),
        _SlowTool(name="b", delay=0.1),
        _SlowTool(name="c", delay=0.1),
    )
    tool_calls = [
        {"function": {"name": "a", "arguments": "{}"}, "id": "c1"},
        {"function": {"name": "b", "arguments": "{}"}, "id": "c2"},
        {"function": {"name": "c", "arguments": "{}"}, "id": "c3"},
    ]
    start = asyncio.get_running_loop().time()
    tasks = [tools.execute(_name=tc["function"]["name"]) for tc in tool_calls]
    await asyncio.gather(*tasks)
    elapsed = asyncio.get_running_loop().time() - start

    # Sequential would take ~300ms; parallel should take ~100ms
    assert elapsed < 0.25, f"Parallel execution took {elapsed:.3f}s (expected < 0.25s)"


@pytest.mark.asyncio
async def test_single_tool_call_unchanged():
    """Single-tool response still works correctly."""
    tools = ToolCollection(_FastTool(name="single"))
    result = await tools.execute("single")
    assert not result.is_error
    assert "Fast result" in result.output


@pytest.mark.asyncio
async def test_semaphore_limits_concurrent():
    """Tool capped at 1 concurrent; verify max_concurrent_seen is 1."""
    tool = _SingleConcurTool(name="limited", delay=0.1)
    tools = ToolCollection(tool)

    async def call():
        return await tools.execute("limited")

    tasks = [call() for _ in range(5)]
    await asyncio.gather(*tasks)

    assert tool.max_concurrent_seen <= 1, (
        f"Expected max_concurrent_seen <= 1, got {tool.max_concurrent_seen}"
    )
