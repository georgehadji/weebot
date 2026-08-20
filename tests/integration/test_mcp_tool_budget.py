"""Integration test: MCP + native tool scoping respects the ≤ 12 tool budget."""

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


class _FakeTool:
    """Lightweight stand-in for BaseTool; only ``name`` is required by ToolCollection."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeBridge:
    """MCPToolRegistryBridge stand-in that returns a fixed external tool subset."""

    def __init__(self, names: list[str]) -> None:
        self.names = list(names)

    async def select_for_query(self, query: str) -> list[str]:
        return list(self.names)


class _FakeNativeSelector:
    """Stand-in NativeToolRetrievalService that returns a fixed native tool subset."""

    def __init__(self, names: list[str]) -> None:
        self.names = list(names)

    async def select_for_query(self, query: str) -> list[str]:
        return list(self.names)


async def _noop_completed_execute(self, context, prompt):
    """Yield a single DoneEvent without scheduling background tasks."""
    yield DoneEvent()


@pytest.fixture
def registry():
    """Registry pre-loaded with 20 native tools and 10 external MCP tools."""
    reg = RoleBasedToolRegistry()
    native_tools = [f"native_tool_{i:02d}" for i in range(20)]
    external_tools = [f"mcp__srv__ext_{i:02d}" for i in range(10)]
    reg.role_mappings = {"admin": native_tools + external_tools}
    return reg


@pytest.mark.asyncio
async def test_tool_collection_stays_within_budget(registry, monkeypatch):
    """With scoping enabled, the final ToolCollection must have ≤ 12 tools."""
    selected_native = ["native_tool_00", "native_tool_05", "native_tool_10", "native_tool_15"]
    selected_external = [
        "mcp__srv__ext_00",
        "mcp__srv__ext_03",
        "mcp__srv__ext_06",
        "mcp__srv__ext_09",
    ]

    bridge = _FakeBridge(names=selected_external)
    selector = _FakeNativeSelector(names=selected_native)

    # Patch tool instantiation so the test does not need real tool dependencies.
    def _fake_create(_self, names, **kwargs):
        return ToolCollection(*[_FakeTool(name=n) for n in names])

    monkeypatch.setattr(RoleBasedToolRegistry, "create_tool_collection_from_names", _fake_create)

    session = Session(id="tool-budget-test")
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

    async for _event in flow.run("do something that needs a few tools"):
        pass

    assert flow._tools is not None
    assert len(flow._tools) <= 12
    tool_names = {t.name for t in flow._tools}
    assert tool_names == set(selected_native) | set(selected_external)


@pytest.mark.asyncio
async def test_unscoped_registry_exceeds_budget(registry, monkeypatch):
    """Without a native selector, native tools are unscoped and the budget is exceeded."""
    selected_external = ["mcp__srv__ext_00", "mcp__srv__ext_01"]
    bridge = _FakeBridge(names=selected_external)

    def _fake_create(_self, names, **kwargs):
        return ToolCollection(*[_FakeTool(name=n) for n in names])

    monkeypatch.setattr(RoleBasedToolRegistry, "create_tool_collection_from_names", _fake_create)

    session = Session(id="tool-budget-unscoped-test")
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_DummyLLMPort(),
            tools=ToolCollection(),
            session=session,
            tool_registry=registry,
            mcp_bridge=bridge,
            native_tool_selector=None,
            max_iterations=1,
        )
    )

    def _resolve_initial_state(*, session, prompt, extra):
        return CompletedState(), session

    monkeypatch.setattr(FlowRouter, "resolve_initial_state", _resolve_initial_state)
    monkeypatch.setattr(CompletedState, "execute", _noop_completed_execute)

    async for _event in flow.run("do something"):
        pass

    assert flow._tools is not None
    # 20 native (unscoped) + 2 external exceeds the 12-tool budget
    assert len(flow._tools) > 12
