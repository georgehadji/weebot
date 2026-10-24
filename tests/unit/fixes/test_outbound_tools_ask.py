"""Outbound/publishing tools always ask, even while the guard chain observes.

Postiz (and agentic-inbox) reach Weebot as MCP tools, namespaced
``mcp__<server>__<tool>``. ``schedulePostTool`` publishes to social accounts and
the generate/clipping tools spend quota; none of that can be taken back. F06's
financial ASK is only logged in observe mode, which is the current mode, so a
name-pattern guard like F06 would still have posted without asking. This guard
(``outbound_policy``, ``WEEBOT_OUTBOUND_TOOL_PATTERNS``) marks its ASK
``enforce_always``: GuardedTool sends it to the approval channel in observe mode
too, unless ``WEEBOT_OUTBOUND_ASK_IN_OBSERVE`` is false.
"""

from __future__ import annotations

import logging

import pytest

from weebot.application.ports.approval_port import ApprovalOutcome
from weebot.application.services.tool_approval import DenyApproval
from weebot.application.services.tool_guards import (
    GuardAction,
    GuardedTool,
    default_guard_chain,
    guard_tools,
    is_outbound_tool,
)
from weebot.domain.models.base_tool import BaseTool
from weebot.domain.models.tool_result import ToolResult


class _Tool(BaseTool):
    calls: int = 0

    async def execute(self, **kwargs):
        self.calls += 1
        return ToolResult(output="ran")


def _tool(name: str) -> _Tool:
    return _Tool(name=name, description="d", parameters={"type": "object", "properties": {}})


class _Approve(DenyApproval):
    async def resolve(self, request):
        return ApprovalOutcome.APPROVED


@pytest.mark.parametrize(
    "name",
    [
        "mcp__postiz__schedulePostTool",
        "mcp__postiz__deletePostTool",
        "mcp__postiz__generateImageTool",
        "mcp__postiz__generateVideoTool",
        "mcp__postiz__clippingTool",
        "mcp__inbox__send_email",
        "mcp__inbox__send_reply",
        "publish_article",
    ],
)
def test_publishing_and_spending_tools_are_outbound(name):
    assert is_outbound_tool(name)


@pytest.mark.parametrize(
    "name",
    [
        "mcp__postiz__postsListTool",
        "mcp__postiz__integrationList",
        "mcp__postiz__mediaStatusTool",
        "mcp__postiz__triggerTool",  # reads provider data (ids, search) for settings
        "mcp__postiz__videoFunctionTool",  # reads voice ids and the like
        "web_search",
        "camofox_browser",
    ],
)
def test_reading_tools_are_not(name):
    assert not is_outbound_tool(name)


def test_only_the_paid_built_in_tools_are_outbound():
    # F54: paid generation and Actor runs ask first; nothing else built in does.
    from weebot.application.services.tool_registry import RoleBasedToolRegistry

    hits = {n for n in RoleBasedToolRegistry.build_tool_class_map() if is_outbound_tool(n)}
    assert hits == {"image_gen", "video_gen", "mixture_of_agents"}


def test_apify_preset_runs_ask():
    from weebot.tools.apify_presets import create_apify_preset_tools

    names = [t.name for t in create_apify_preset_tools(object())]
    assert names and all(is_outbound_tool(n) for n in names)


def test_the_chain_asks_and_marks_it_enforced():
    verdict = default_guard_chain().evaluate("mcp__postiz__schedulePostTool", {}).verdict
    assert verdict.action is GuardAction.ASK and verdict.guard == "outbound_policy"
    assert verdict.enforce_always


async def test_observe_mode_still_asks_for_an_outbound_tool():
    inner = _tool("mcp__postiz__schedulePostTool")
    (tool,) = guard_tools([inner], mode="observe")
    assert isinstance(tool, GuardedTool)
    tool._approval = DenyApproval()
    result = await tool.execute(type="now")
    assert result.is_error and inner.calls == 0


async def test_an_approved_outbound_call_runs_in_observe_mode():
    inner = _tool("mcp__postiz__schedulePostTool")
    (tool,) = guard_tools([inner], mode="observe")
    tool._approval = _Approve()
    await tool.execute(type="now")
    assert inner.calls == 1


async def test_other_asks_in_observe_mode_still_only_log(caplog):
    inner = _tool("payout_create")  # financial ASK, not outbound
    (tool,) = guard_tools([inner], mode="observe")
    tool._approval = DenyApproval()
    with caplog.at_level(logging.WARNING):
        await tool.execute()
    assert inner.calls == 1


async def test_the_observe_override_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("WEEBOT_OUTBOUND_ASK_IN_OBSERVE", "false")
    inner = _tool("mcp__postiz__schedulePostTool")
    (tool,) = guard_tools([inner], mode="observe")
    tool._approval = DenyApproval()
    await tool.execute()
    assert inner.calls == 1


def test_the_patterns_are_a_setting(monkeypatch):
    monkeypatch.setenv("WEEBOT_OUTBOUND_TOOL_PATTERNS", "*announce*")
    assert is_outbound_tool("announce_release")
    assert not is_outbound_tool("publish_article")
    # The setting adds names; it cannot un-gate an MCP write (F38 fails closed).
    assert is_outbound_tool("mcp__postiz__schedulePostTool")


async def test_build_tools_wraps_an_mcp_outbound_tool():
    from weebot.interfaces.factories import build_tools

    collection = await build_tools(
        role="researcher", extra_tools=[_tool("mcp__postiz__schedulePostTool")]
    )
    assert isinstance(collection.get_tool("mcp__postiz__schedulePostTool"), GuardedTool)


# MCP tools fail closed: a write that no name pattern lists still asks. Jira,
# HubSpot and Apify writes went straight through before (Wave G, F38).
@pytest.mark.parametrize(
    "name",
    [
        "mcp__jira__jira_create_issue",
        "mcp__jira__jira_delete_issue",
        "mcp__jira__jira_transition_issue",
        "mcp__jira__jira_add_comment",
        "mcp__hubspot__hubspot_batch_create_objects",
        "mcp__hubspot__hubspot_batch_update_objects",
        "mcp__hubspot__hubspot_create_engagement",
        "mcp__apify__call_actor",
        "mcp__apify__abort_actor_run",
        "mcp__apify__apify__rag_web_browser",  # runs a billed Actor
        "mcp__postiz__uploadFromUrlTool",
        "mcp__someserver__frobnicate",  # unknown verb: ask
    ],
)
def test_mcp_writes_ask_even_without_a_pattern(name):
    assert is_outbound_tool(name)


@pytest.mark.parametrize(
    "name",
    [
        "mcp__jira__jira_get_issue",
        "mcp__jira__jira_search",
        "mcp__jira__jira_get_all_projects",
        "mcp__jira__jira_download_attachments",
        "mcp__jira__jira_batch_get_changelogs",
        "mcp__hubspot__hubspot_list_objects",
        "mcp__hubspot__hubspot_get_link",
        "mcp__hubspot__hubspot_batch_read_objects",
        "mcp__apify__search_actors",
        "mcp__apify__fetch_actor_details",
        "mcp__apify__get_dataset_items",
        "mcp__apify__apify__web_fetch",
        "mcp__postiz__integrationSchema",
        "mcp__postiz__groupList",
    ],
)
def test_mcp_reads_do_not_ask(name):
    assert not is_outbound_tool(name)
