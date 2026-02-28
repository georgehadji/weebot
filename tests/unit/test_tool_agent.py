"""Unit tests for ToolCallWeebotAgent (ReAct loop)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from weebot.tools.base import BaseTool, ToolResult, ToolCollection
from weebot.domain.models import AgentState
from weebot.core.tool_agent import ToolCallWeebotAgent


class UpperTool(BaseTool):
    name: str = "uppercase"
    description: str = "Converts text to uppercase"
    parameters: dict = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, text: str) -> ToolResult:
        return ToolResult(output=text.upper())


def _make_finish_response(content: str):
    """OpenAI-like response with no tool calls (agent finishes)."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_tool_call_response(tool_name: str, args: dict, call_id: str = "call_1"):
    """OpenAI-like response with one tool call."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(args)
    msg = MagicMock()
    msg.content = ""
    msg.tool_calls = [tc]
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.asyncio
async def test_agent_finishes_without_tools():
    """Agent returns LLM content when no tool calls are made."""
    agent = ToolCallWeebotAgent(tools=ToolCollection(UpperTool()))

    mock_create = AsyncMock(return_value=_make_finish_response("Done!"))
    with patch.object(agent._client.chat.completions, "create", mock_create):
        result = await agent.run("say done")

    assert result == "Done!"
    assert agent.state == AgentState.FINISHED


@pytest.mark.asyncio
async def test_agent_calls_tool_then_finishes():
    """Agent calls tool, gets result, then finishes on next LLM call."""
    agent = ToolCallWeebotAgent(tools=ToolCollection(UpperTool()))

    responses = [
        _make_tool_call_response("uppercase", {"text": "hello"}, "call_1"),
        _make_finish_response("I uppercased it: HELLO"),
    ]
    mock_create = AsyncMock(side_effect=responses)
    with patch.object(agent._client.chat.completions, "create", mock_create):
        result = await agent.run("uppercase hello")

    assert "HELLO" in result
    assert mock_create.call_count == 2


@pytest.mark.asyncio
async def test_agent_handles_tool_error_gracefully():
    """Agent continues when tool raises an exception."""

    class BrokenTool(BaseTool):
        name: str = "broken"
        description: str = "Broken"
        parameters: dict = {"type": "object", "properties": {}}

        async def execute(self) -> ToolResult:
            raise RuntimeError("tool crashed")

    agent = ToolCallWeebotAgent(tools=ToolCollection(BrokenTool()))
    responses = [
        _make_tool_call_response("broken", {}, "call_1"),
        _make_finish_response("I encountered an error"),
    ]
    mock_create = AsyncMock(side_effect=responses)
    with patch.object(agent._client.chat.completions, "create", mock_create):
        result = await agent.run("break it")

    assert result  # agent recovered and returned something


def test_agent_initial_state():
    agent = ToolCallWeebotAgent(tools=ToolCollection())
    assert agent.state == AgentState.IDLE
