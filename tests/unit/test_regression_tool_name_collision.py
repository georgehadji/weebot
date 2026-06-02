"""Regression test: ToolCollection.execute name collision with tool parameters.

BUG: ToolCollection.execute(self, name, **kwargs) used 'name' as the
dispatch parameter.  Any tool with a parameter also called 'name'
(e.g. design_system_tool) caused::

    TypeError: ToolCollection.execute() got multiple values for argument 'name'

FIX: Renamed the dispatch parameter to '_name' (leading underscore)
so it never collides with tool-defined parameters.
"""
from __future__ import annotations

from weebot.application.models.tool_collection import ToolCollection
from weebot.tools.base import BaseTool, ToolResult


class ToolWithNameParam(BaseTool):
    name: str = "test_tool"
    description: str = "A tool that accepts a 'name' parameter"
    parameters: dict = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "A name parameter"},
        },
    }

    async def execute(self, name: str = "", **kwargs) -> ToolResult:
        return ToolResult(output=f"name={name}")


def test_name_param_does_not_collide_with_dispatch():
    """Passing 'name' as a tool parameter must not collide with the
    execute() dispatch argument."""
    tc = ToolCollection(ToolWithNameParam())

    import asyncio

    result = asyncio.run(tc.execute(_name="test_tool", name="hello"))
    assert not result.is_error, f"Unexpected error: {result.error}"
    assert result.output == "name=hello"


def test_unknown_tool_still_reports_correctly():
    """Error message for unknown tool must still use the tool name."""
    tc = ToolCollection()

    import asyncio

    result = asyncio.run(tc.execute(_name="nonexistent"))
    assert result.is_error
    assert "nonexistent" in result.error
