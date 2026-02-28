"""Unit tests for PlanningTool and PlanningFlow."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.flow.planning import PlanningFlow, PlanningTool
from weebot.tools.base import BaseTool, ToolCollection, ToolResult


# ---------------------------------------------------------------------------
# PlanningTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planning_tool_create():
    tool = PlanningTool()
    result = await tool.execute(
        command="create",
        plan_id="p1",
        title="My Plan",
        steps=["step 1", "step 2"],
    )
    assert not result.is_error
    assert "My Plan" in result.output
    assert "step 1" in result.output


@pytest.mark.asyncio
async def test_planning_tool_update_step():
    tool = PlanningTool()
    await tool.execute(command="create", plan_id="p1", title="T", steps=["s1"])
    result = await tool.execute(
        command="update_step", plan_id="p1", step_index=0, status="completed"
    )
    assert not result.is_error
    assert "completed" in result.output


@pytest.mark.asyncio
async def test_planning_tool_get_shows_steps():
    tool = PlanningTool()
    await tool.execute(command="create", plan_id="p1", title="T", steps=["s1", "s2"])
    result = await tool.execute(command="get", plan_id="p1")
    assert not result.is_error
    assert "s1" in result.output
    assert "s2" in result.output


@pytest.mark.asyncio
async def test_planning_tool_missing_plan_is_error():
    tool = PlanningTool()
    result = await tool.execute(command="get", plan_id="nonexistent")
    assert result.is_error


@pytest.mark.asyncio
async def test_planning_tool_clear():
    tool = PlanningTool()
    await tool.execute(command="create", plan_id="p1", title="T", steps=["s1"])
    result = await tool.execute(command="clear", plan_id="p1")
    assert not result.is_error
    # After clear, get should fail
    get_result = await tool.execute(command="get", plan_id="p1")
    assert get_result.is_error


@pytest.mark.asyncio
async def test_planning_tool_update_step_invalid_index():
    tool = PlanningTool()
    await tool.execute(command="create", plan_id="p1", title="T", steps=["only one"])
    result = await tool.execute(
        command="update_step", plan_id="p1", step_index=99, status="completed"
    )
    assert result.is_error


@pytest.mark.asyncio
async def test_planning_tool_unknown_command():
    tool = PlanningTool()
    result = await tool.execute(command="delete", plan_id="p1")
    assert result.is_error


def test_planning_tool_to_param():
    tool = PlanningTool()
    param = tool.to_param()
    assert param["function"]["name"] == "planning"
    assert "command" in param["function"]["parameters"]["required"]


# ---------------------------------------------------------------------------
# PlanningFlow
# ---------------------------------------------------------------------------


class EchoTool(BaseTool):
    name: str = "echo"
    description: str = "Echo text back"
    parameters: dict = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, text: str, **_) -> ToolResult:
        return ToolResult(output=f"Echo: {text}")


def _finish_response(content: str):
    """Build a minimal mock OpenAI ChatCompletion response with no tool calls."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.asyncio
async def test_planning_flow_run_returns_output():
    flow = PlanningFlow(tools=ToolCollection(EchoTool()))
    mock_create = AsyncMock(return_value=_finish_response("Plan complete"))
    with patch.object(flow._agent._client.chat.completions, "create", mock_create):
        result = await flow.run("Do something useful")
    assert result  # non-empty output


@pytest.mark.asyncio
async def test_planning_flow_has_planning_tool():
    """PlanningFlow always includes a PlanningTool in its agent."""
    flow = PlanningFlow()
    tool_names = [t.name for t in flow._agent.tools]
    assert "planning" in tool_names
