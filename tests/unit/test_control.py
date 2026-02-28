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
async def test_ask_human_returns_stripped_answer():
    """AskHumanTool strips whitespace from the human's answer."""
    tool = AskHumanTool()

    async def answer_coro():
        return "  yes  "

    mock_loop = MagicMock()
    mock_loop.run_in_executor = MagicMock(return_value=answer_coro())

    with patch("weebot.tools.control.asyncio.get_event_loop", return_value=mock_loop):
        result = await tool.execute(question="Are you ready?")

    assert not result.is_error
    assert result.output == "yes"


def test_ask_human_to_param_name():
    tool = AskHumanTool()
    param = tool.to_param()
    assert param["function"]["name"] == "ask_human"


def test_ask_human_to_param_requires_question():
    tool = AskHumanTool()
    param = tool.to_param()
    assert "question" in param["function"]["parameters"]["required"]
