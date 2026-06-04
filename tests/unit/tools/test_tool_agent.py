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


def _make_two_tool_call_response(
    tool1: str, args1: dict, id1: str,
    tool2: str, args2: dict, id2: str,
):
    """OpenAI-like response with two tool calls (parallel)."""
    def _tc(name, args, cid):
        tc = MagicMock()
        tc.id = cid
        tc.function.name = name
        tc.function.arguments = json.dumps(args)
        return tc

    msg = MagicMock()
    msg.content = ""
    msg.tool_calls = [_tc(tool1, args1, id1), _tc(tool2, args2, id2)]
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.asyncio
async def test_act_executes_two_tool_calls_concurrently():
    """Two tool calls in one response must both be executed and appended to memory."""
    import asyncio

    execution_order: list[str] = []

    class SlowTool(BaseTool):
        name: str = "slow"
        description: str = "Slow tool"
        parameters: dict = {"type": "object", "properties": {"tag": {"type": "string"}}, "required": ["tag"]}

        async def execute(self, tag: str, **_) -> ToolResult:
            await asyncio.sleep(0)   # yield to event loop
            execution_order.append(tag)
            return ToolResult(output=f"done-{tag}")

    agent = ToolCallWeebotAgent(tools=ToolCollection(SlowTool()))

    responses = [
        _make_two_tool_call_response("slow", {"tag": "a"}, "c1", "slow", {"tag": "b"}, "c2"),
        _make_finish_response("both done"),
    ]
    mock_create = AsyncMock(side_effect=responses)
    with patch.object(agent._client.chat.completions, "create", mock_create):
        await agent.run("run both")

    # Both tool results must be in memory (as TOOL messages)
    from weebot.domain.models import Role
    tool_msgs = [m for m in agent.memory.messages if m.role == Role.TOOL]
    assert len(tool_msgs) == 2
    ids = {m.tool_call_id for m in tool_msgs}
    assert ids == {"c1", "c2"}
