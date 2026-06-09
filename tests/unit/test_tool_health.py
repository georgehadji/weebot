"""Tests for Phase 3: Per-tool timeouts and health checks."""
import pytest
from unittest.mock import AsyncMock, patch

from weebot.tools.base import BaseTool, ToolResult
from weebot.application.models.tool_collection import ToolCollection


class _HealthyTool(BaseTool):
    """Tool that always reports healthy."""
    name: str = "healthy_tool"
    description: str = "Healthy test tool"
    parameters: dict = {"type": "object", "properties": {}}
    default_timeout_seconds: int = 30

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult.success_result(output="OK")

    async def health_check(self) -> bool:
        return True


class _UnhealthyTool(BaseTool):
    """Tool that reports unhealthy."""
    name: str = "unhealthy_tool"
    description: str = "Unhealthy test tool"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult.success_result(output="Should not be called")

    async def health_check(self) -> bool:
        return False


class _TimeoutTool(BaseTool):
    """Tool with a specific timeout."""
    name: str = "timeout_tool"
    description: str = "Timeout test tool"
    parameters: dict = {"type": "object", "properties": {}}
    default_timeout_seconds: int = 120

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult.success_result(output="OK")


@pytest.mark.asyncio
async def test_healthy_tool_appears_in_params():
    """Tool with health_check -> True is included in to_params()."""
    tools = ToolCollection(_HealthyTool())
    # Before health check: should appear
    params = tools.to_params()
    names = [p["function"]["name"] for p in params]
    assert "healthy_tool" in names

    # After health check: should still appear
    await tools.check_health()
    params = tools.to_params()
    names = [p["function"]["name"] for p in params]
    assert "healthy_tool" in names


@pytest.mark.asyncio
async def test_unhealthy_tool_excluded_from_params():
    """Tool with health_check -> False is excluded from to_params()."""
    tools = ToolCollection(_UnhealthyTool())
    await tools.check_health()
    params = tools.to_params()
    names = [p["function"]["name"] for p in params]
    assert "unhealthy_tool" not in names


@pytest.mark.asyncio
async def test_health_check_not_run_uses_all_tools():
    """Before check_health(), all tools appear in to_params()."""
    tools = ToolCollection(_UnhealthyTool())
    params = tools.to_params()
    names = [p["function"]["name"] for p in params]
    assert "unhealthy_tool" in names  # appears because health check hasn't run


@pytest.mark.asyncio
async def test_unhealthy_tool_execution_blocked():
    """Executing an unhealthy tool returns an error."""
    tools = ToolCollection(_UnhealthyTool())
    await tools.check_health()
    result = await tools.execute("unhealthy_tool")
    assert result.is_error
    assert "unavailable" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_per_tool_timeout_attribute():
    """Tool has correct default_timeout_seconds."""
    tool = _TimeoutTool()
    assert tool.default_timeout_seconds == 120

    # Default BaseTool timeout should be 60
    class DefaultTool(BaseTool):
        name: str = "default"
        description: str = "Default timeout"
        parameters: dict = {"type": "object", "properties": {}}
        async def execute(self, **kwargs) -> ToolResult:
            return ToolResult.success_result(output="OK")

    default_tool = DefaultTool()
    assert default_tool.default_timeout_seconds == 60


@pytest.mark.asyncio
async def test_check_health_returns_dict():
    """check_health() returns a dict of tool_name -> bool."""
    tools = ToolCollection(
        _HealthyTool(),
        _UnhealthyTool(),
    )
    health = await tools.check_health()
    assert isinstance(health, dict)
    assert health["healthy_tool"] is True
    assert health["unhealthy_tool"] is False
