"""Unit tests for BaseTool protocol, ToolResult, and ToolCollection."""
import pytest
from weebot.tools.base import BaseTool, ToolResult, ToolCollection


class EchoTool(BaseTool):
    name: str = "echo"
    description: str = "Echoes input back"
    parameters: dict = {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "Text to echo"}},
        "required": ["text"],
    }

    async def execute(self, text: str) -> ToolResult:
        return ToolResult(output=f"Echo: {text}")


class FailTool(BaseTool):
    name: str = "fail"
    description: str = "Always fails"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self) -> ToolResult:
        return ToolResult(output="", error="always fails")


def test_tool_result_success():
    r = ToolResult(output="hello")
    assert r.output == "hello"
    assert r.error is None
    assert r.is_error is False


def test_tool_result_error():
    r = ToolResult(output="", error="oops")
    assert r.is_error is True


def test_tool_to_param():
    tool = EchoTool()
    param = tool.to_param()
    assert param["type"] == "function"
    assert param["function"]["name"] == "echo"
    assert "text" in param["function"]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_echo_tool_execute():
    tool = EchoTool()
    result = await tool.execute(text="hello")
    assert result.output == "Echo: hello"


@pytest.mark.asyncio
async def test_tool_collection_execute():
    col = ToolCollection(EchoTool(), FailTool())
    result = await col.execute("echo", text="world")
    assert result.output == "Echo: world"


@pytest.mark.asyncio
async def test_tool_collection_unknown():
    col = ToolCollection(EchoTool())
    result = await col.execute("nonexistent")
    assert result.is_error
    assert "nonexistent" in result.error


def test_tool_collection_to_params():
    col = ToolCollection(EchoTool(), FailTool())
    params = col.to_params()
    assert len(params) == 2
    assert params[0]["function"]["name"] == "echo"
