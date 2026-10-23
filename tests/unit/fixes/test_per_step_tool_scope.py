"""Each step is sent the tools it needs, not all of them (ICM B1).

Measured 2026-10-23: every executor call sent all 171 tool definitions (57
built-in, 114 MCP), about 49k of the ~53k prompt tokens, even for a weather
lookup. A step now gets a core set, the tools its category and wording call
for, and the MCP tools of services it names; every tool stays callable by name
(tasks/audits/icm_optimization_2026_10_23.md).
"""

from __future__ import annotations

from weebot.application.models.tool_collection import ToolCollection
from weebot.application.services.tool_scope import select_tools
from weebot.domain.models.base_tool import BaseTool
from weebot.domain.models.tool_result import ToolResult

_ALL = {
    "web_search", "file_editor", "python_execute", "bash", "powershell", "advanced_browser",
    "ask_human", "terminate", "todo_write", "weather", "image_gen", "vane_search",
    "atomic_mail", "computer_use", "mcp__jira__jira_create_issue", "mcp__jira__jira_search",
    "mcp__hubspot__hubspot_search_objects", "mcp__apify__call_actor",
    "mcp__postiz__integrationSchedulePostTool",
}


def test_a_weather_step_gets_the_core_and_weather_not_mcp():
    got = select_tools("Look up today's weather in Athens", _ALL)
    assert {"web_search", "weather", "file_editor"} <= got
    assert not any(n.startswith("mcp__") for n in got)
    assert "image_gen" not in got


def test_a_jira_step_gets_the_jira_tools_only():
    got = select_tools("Create a Jira ticket for the login bug", _ALL)
    assert {"mcp__jira__jira_create_issue", "mcp__jira__jira_search"} <= got
    assert "mcp__hubspot__hubspot_search_objects" not in got


def test_crm_words_bring_hubspot_and_a_named_tool_is_always_included():
    assert "mcp__hubspot__hubspot_search_objects" in select_tools("Find the deal in our CRM", _ALL)
    assert "computer_use" in select_tools("Use computer_use to click OK", _ALL)


def test_an_image_step_gets_image_gen():
    assert "image_gen" in select_tools("Generate a logo image for the cafe", _ALL)


class _T(BaseTool):
    async def execute(self, **kw):
        return ToolResult(output=self.name)


def _tool(name):
    return _T(name=name, description="d", parameters={"type": "object", "properties": {}})


async def test_hidden_tools_are_not_sent_but_still_callable():
    tools = ToolCollection(_tool("web_search"), _tool("image_gen"))
    tools.set_visible({"web_search"})
    assert [p["function"]["name"] for p in tools.to_params()] == ["web_search"]
    assert tools.hidden_names() == ["image_gen"]
    assert (await tools.execute("image_gen")).output == "image_gen"
    tools.set_visible(None)
    assert len(tools.to_params()) == 2


def test_the_executor_scopes_its_collection_per_step(monkeypatch):
    from types import SimpleNamespace

    from weebot.application.agents.executor._base import ExecutorAgent
    from weebot.config import feature_flags

    monkeypatch.setattr(feature_flags, "TOOL_SCOPE_ENABLED", True)
    tools = ToolCollection(_tool("web_search"), _tool("image_gen"), _tool("mcp__jira__jira_search"))
    agent = SimpleNamespace(_tools=tools)
    note = ExecutorAgent._scope_tools_for(agent, SimpleNamespace(description="Search the web for X"))
    assert [p["function"]["name"] for p in tools.to_params()] == ["web_search"]
    assert "image_gen" in note and "mcp__jira__jira_search" in note

    monkeypatch.setattr(feature_flags, "TOOL_SCOPE_ENABLED", False)
    assert ExecutorAgent._scope_tools_for(agent, SimpleNamespace(description="x")) == ""
    assert len(tools.to_params()) == 3
