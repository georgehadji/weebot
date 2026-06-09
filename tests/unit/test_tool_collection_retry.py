"""Tests for Phase 1: Retry activation in ToolCollection."""
import pytest
from unittest.mock import AsyncMock, patch

from weebot.tools.base import BaseTool, ToolResult
from weebot.application.models.tool_collection import ToolCollection


class _RetryableTool(BaseTool):
    """Tool that raises OSError on first call, succeeds on second."""
    name: str = "test_retry"
    description: str = "Test tool for retry"
    parameters: dict = {"type": "object", "properties": {}}
    _call_count: int = 0

    async def execute(self, **kwargs) -> ToolResult:
        self._call_count += 1
        if self._call_count == 1:
            raise OSError("Transient failure")
        return ToolResult.success_result(output="Success on retry")


class _NonRetryableTool(BaseTool):
    """Tool that raises ValueError — should NOT be retried."""
    name: str = "test_non_retry"
    description: str = "Non-retryable test tool"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> ToolResult:
        raise ValueError("Bad arguments")


@pytest.mark.asyncio
async def test_retries_on_os_error():
    """Verify exponential backoff fires up to 2 times."""
    tool = _RetryableTool()
    tool._call_count = 0
    collection = ToolCollection(tool)
    result = await collection.execute("test_retry")
    assert not result.is_error
    assert "Success on retry" in result.output
    assert tool._call_count == 2  # first failed, second succeeded


@pytest.mark.asyncio
async def test_no_retry_on_value_error():
    """Verify non-retryable exceptions surface on first attempt."""
    collection = ToolCollection(_NonRetryableTool())
    result = await collection.execute("test_non_retry")
    assert result.is_error
    assert "Bad arguments" in result.error
    # metadata should show retry_count=0 since ValueError is not retryable
    assert result.metadata.get("retry_count") == 0


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt():
    """Mock tool raises once, succeeds second time."""
    tool = _RetryableTool()
    tool._call_count = 0
    collection = ToolCollection(tool)
    result = await collection.execute("test_retry")
    assert not result.is_error
    assert tool._call_count == 2


@pytest.mark.asyncio
async def test_default_max_retries():
    """Verify DEFAULT_MAX_RETRIES is 2."""
    assert ToolCollection.DEFAULT_MAX_RETRIES == 2
    assert OSError in ToolCollection.RETRYABLE_EXCEPTIONS
    assert TimeoutError in ToolCollection.RETRYABLE_EXCEPTIONS
    assert ConnectionError in ToolCollection.RETRYABLE_EXCEPTIONS
