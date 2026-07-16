"""Integration test: PlanActFlow scopes MCP tools per query (H1)."""
from __future__ import annotations

import pytest

from weebot.application.flows.flow_router import FlowRouter
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.completed import CompletedState
from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.event import DoneEvent
from weebot.domain.models.llm_response import LLMResponse
from weebot.domain.models.session import Session
from weebot.tools.tool_registry import RoleBasedToolRegistry


class _DummyLLMPort(LLMPort):
    """Minimal LLMPort for integration tests."""

    async def chat(
        self,
        messages,
        tools=None,
        tool_choice="auto",
        response_format=None,
        model=None,
        temperature=None,
        max_tokens=None,
    ) -> LLMResponse:
        return LLMResponse(content="", model="dummy")


class _FakeBridge:
    """MCPToolRegistryBridge stand-in that records select_for_query calls."""

    def __init__(self, names: list[str] | None = None) -> None:
        self.names = names or ["mcp__srv__scoped_tool"]
        self.selected_calls: list[str] = []

    async def select_for_query(self, query: str) -> list[str]:
        self.selected_calls.append(query)
        return list(self.names)


async def _noop_completed_execute(self, context, prompt):
    """Yield a single DoneEvent without scheduling background tasks."""
    yield DoneEvent()


@pytest.fixture
def registry():
    """Lightweight registry with an empty admin role."""
    reg = RoleBasedToolRegistry()
    reg.role_mappings = {"admin": []}
    return reg


@pytest.mark.asyncio
async def test_plan_act_flow_calls_select_for_query_on_run(registry, monkeypatch):
    """PlanActFlow.run should invoke bridge.select_for_query(effective_prompt)."""
    bridge = _FakeBridge()
    session = Session(id="scoped-flow-test")
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_DummyLLMPort(),
            tools=ToolCollection(),
            session=session,
            tool_registry=registry,
            mcp_bridge=bridge,
            max_iterations=1,
        )
    )

    # Short-circuit state machine so we only exercise the run() preamble.
    def _resolve_initial_state(*, session, prompt, extra):
        return CompletedState(), session

    monkeypatch.setattr(FlowRouter, "resolve_initial_state", _resolve_initial_state)
    monkeypatch.setattr(CompletedState, "execute", _noop_completed_execute)

    events = []
    async for event in flow.run("search the web for MCP patterns"):
        events.append(event)

    assert bridge.selected_calls == ["search the web for MCP patterns"]
    assert any(e.type == "done" for e in events)


@pytest.mark.asyncio
async def test_plan_act_flow_survives_missing_bridge(registry, monkeypatch):
    """Without an MCP bridge the flow should still start without error."""
    session = Session(id="scoped-flow-test-no-bridge")
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_DummyLLMPort(),
            tools=ToolCollection(),
            session=session,
            tool_registry=registry,
            mcp_bridge=None,
            max_iterations=1,
        )
    )

    def _resolve_initial_state(*, session, prompt, extra):
        return CompletedState(), session

    monkeypatch.setattr(FlowRouter, "resolve_initial_state", _resolve_initial_state)
    monkeypatch.setattr(CompletedState, "execute", _noop_completed_execute)

    # Just verifying the scoping preamble is a no-op and does not raise.
    async for _event in flow.run("do something"):
        pass


@pytest.mark.asyncio
async def test_plan_act_flow_does_not_mutate_registry(registry, monkeypatch):
    """With a non-mutating bridge, PlanActFlow.run must leave registry intact."""
    original_tools = ["bash", "web_search"]
    registry.role_mappings = {"admin": list(original_tools)}
    bridge = _FakeBridge(names=["mcp__srv__scoped_tool"])

    session = Session(id="scoped-flow-registry-intact")
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_DummyLLMPort(),
            tools=ToolCollection(),
            session=session,
            tool_registry=registry,
            mcp_bridge=bridge,
            max_iterations=1,
        )
    )

    def _resolve_initial_state(*, session, prompt, extra):
        return CompletedState(), session

    monkeypatch.setattr(FlowRouter, "resolve_initial_state", _resolve_initial_state)
    monkeypatch.setattr(CompletedState, "execute", _noop_completed_execute)

    async for _event in flow.run("search the web"):
        pass

    assert registry.get_tools_for_role("admin") == original_tools


class _FakeNativeSelector:
    """Stand-in NativeToolRetrievalService that returns a fixed subset."""

    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.selected_calls: list[str] = []

    async def select_for_query(self, query: str) -> list[str]:
        self.selected_calls.append(query)
        return list(self.names)


@pytest.mark.asyncio
async def test_plan_act_flow_scopes_native_tools_when_selector_provided(registry, monkeypatch):
    """With a native selector, only selected native tools remain in the collection."""
    registry.role_mappings = {"admin": ["bash", "web_search", "python_execute"]}
    bridge = _FakeBridge(names=["mcp__srv__scoped_tool"])
    selector = _FakeNativeSelector(names=["web_search"])

    session = Session(id="scoped-flow-native")
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_DummyLLMPort(),
            tools=ToolCollection(),
            session=session,
            tool_registry=registry,
            mcp_bridge=bridge,
            native_tool_selector=selector,
            max_iterations=1,
        )
    )

    def _resolve_initial_state(*, session, prompt, extra):
        return CompletedState(), session

    monkeypatch.setattr(FlowRouter, "resolve_initial_state", _resolve_initial_state)
    monkeypatch.setattr(CompletedState, "execute", _noop_completed_execute)

    async for _event in flow.run("search the web"):
        pass

    assert selector.selected_calls == ["search the web"]
    # Registry must remain unchanged (non-mutating)
    assert registry.get_tools_for_role("admin") == ["bash", "web_search", "python_execute"]
