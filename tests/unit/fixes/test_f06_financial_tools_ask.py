"""F06: financial and payment tools always ask (remaining-fix plan B1, decision 3).

`TOOL_CATEGORIES` maps `finance`/`payment` to FORCE_ALWAYS_ASK and the setting
`financial_tools_always_ask` defaults to True, but no tool carried a category
and the guard chain wrapped only bash, powershell and python_execute, so the
rule could never fire. A payment tool can only arrive from an external MCP
server, so it is recognised by name (`WEEBOT_FINANCIAL_TOOL_PATTERNS`).
In observe mode the ASK is logged; in enforce mode it goes to the approval
channel like any other ASK.
"""

from __future__ import annotations

import logging

from weebot.application.ports.approval_port import ApprovalOutcome
from weebot.application.services.tool_approval import DenyApproval
from weebot.application.services.tool_guards import (
    GuardAction,
    GuardedTool,
    default_guard_chain,
    guard_tools,
    is_financial_tool,
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


def test_payment_tools_are_recognised_by_name():
    assert is_financial_tool("mcp_stripe__create_refund")
    assert is_financial_tool("Create_Invoice")
    assert not is_financial_tool("web_search")


def test_the_chain_asks_for_a_financial_tool():
    verdict = default_guard_chain().evaluate("mcp_stripe__create_refund", {"amount": 5}).verdict
    assert verdict.action is GuardAction.ASK
    assert verdict.guard == "financial_policy"


def test_financial_tools_are_wrapped_and_others_are_not():
    wrapped = guard_tools([_tool("mcp_stripe__create_refund"), _tool("web_search")])
    assert isinstance(wrapped[0], GuardedTool)
    assert not isinstance(wrapped[1], GuardedTool)


async def test_observe_mode_logs_and_runs(caplog):
    inner = _tool("payout_create")
    (tool,) = guard_tools([inner], mode="observe")
    with caplog.at_level(logging.WARNING):
        result = await tool.execute(amount=5)
    assert result.output == "ran" and inner.calls == 1
    assert "financial_policy" in caplog.text


async def test_enforce_mode_asks_and_deny_refuses():
    inner = _tool("payout_create")
    (tool,) = guard_tools([inner], mode="enforce")
    tool._approval = DenyApproval()
    result = await tool.execute(amount=5)
    assert result.is_error and inner.calls == 0


async def test_enforce_mode_runs_when_approved():
    class _Approve(DenyApproval):
        async def resolve(self, request):
            return ApprovalOutcome.APPROVED

    inner = _tool("payout_create")
    (tool,) = guard_tools([inner], mode="enforce")
    tool._approval = _Approve()
    await tool.execute(amount=5)
    assert inner.calls == 1


async def test_build_tools_wraps_a_financial_tool_added_after_the_registry():
    from weebot.interfaces.factories import build_tools

    collection = await build_tools(role="researcher", extra_tools=[_tool("mcp_stripe__refund")])
    assert isinstance(collection.get_tool("mcp_stripe__refund"), GuardedTool)


def test_the_setting_turns_it_off(monkeypatch):
    monkeypatch.setenv("FINANCIAL_TOOLS_ALWAYS_ASK", "false")
    verdict = default_guard_chain().evaluate("mcp_stripe__create_refund", {}).verdict
    assert verdict.action is GuardAction.ALLOW


def test_the_patterns_are_a_setting(monkeypatch):
    monkeypatch.setenv("WEEBOT_FINANCIAL_TOOL_PATTERNS", "*ledger_post*")
    assert is_financial_tool("acct_ledger_post")
    assert not is_financial_tool("mcp_stripe__create_refund")
