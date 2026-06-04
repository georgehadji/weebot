"""Unit tests for TerminateTool and AskHumanTool."""
import pytest
from unittest.mock import MagicMock, patch

from weebot.tools.control import AskHumanTool, TerminateTool


# ---------------------------------------------------------------------------
# TerminateTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminate_includes_reason_in_output():
    tool = TerminateTool()
    result = await tool.execute(reason="All done")
    assert not result.is_error
    assert "All done" in result.output


@pytest.mark.asyncio
async def test_terminate_is_not_error():
    tool = TerminateTool()
    result = await tool.execute(reason="finished")
    assert not result.is_error


def test_terminate_to_param_name():
    tool = TerminateTool()
    param = tool.to_param()
    assert param["function"]["name"] == "terminate"


def test_terminate_to_param_requires_reason():
    tool = TerminateTool()
    param = tool.to_param()
    assert "reason" in param["function"]["parameters"]["required"]


# ---------------------------------------------------------------------------
# AskHumanTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_human_returns_special_result():
    """AskHumanTool returns a special result indicating human input is needed.
    
    The tool now returns a ToolResult with awaiting_human flag instead of
    blocking on input. This enables the HITL (Human-in-the-Loop) flow.
    """
    tool = AskHumanTool()
    
    result = await tool.execute(question="Are you ready?")
    
    # Tool should return a result (not block)
    assert result is not None
    # Result should indicate human interaction is needed
    assert result.data.get("awaiting_human") is True
    assert result.data.get("question") == "Are you ready?"


def test_ask_human_to_param_name():
    tool = AskHumanTool()
    param = tool.to_param()
    assert param["function"]["name"] == "ask_human"


def test_ask_human_to_param_requires_question():
    tool = AskHumanTool()
    param = tool.to_param()
    assert "question" in param["function"]["parameters"]["required"]
