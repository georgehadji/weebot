"""Unit tests for MCP-related DI factory wiring (H1 scoped aggregation)."""
from __future__ import annotations

import pytest

from weebot.application.di import Container
from weebot.application.di._factories import FactoriesMixin
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.ports.llm_port import LLMPort
from weebot.application.services.mcp_tool_retrieval_service import (
    McpToolRetrievalService,
)
from weebot.config.constants import MCP_DEFAULT_SCOPE_K
from weebot.domain.models.session import Session
from weebot.tools.tool_registry import RoleBasedToolRegistry


class _DummyLLMPort(LLMPort):
    """Minimal LLMPort stand-in for factory tests."""

    async def chat(
        self,
        messages,
        tools=None,
        tool_choice="auto",
        response_format=None,
        model=None,
        temperature=None,
        max_tokens=None,
    ):
        from weebot.domain.models.llm_response import LLMResponse

        return LLMResponse(content="", model="dummy")


class _DummyBridge:
    """Stand-in MCPToolRegistryBridge with a scope_for_query hook."""

    def __init__(self) -> None:
        self.scoped_calls: list[str] = []

    async def scope_for_query(self, query: str) -> list[str]:
        self.scoped_calls.append(query)
        return ["mcp__srv__dummy"]


@pytest.fixture
def container(tmp_path, monkeypatch):
    """A configured container with heavy adapters replaced by dummies."""
    c = Container()

    # Avoid real LLM adapter construction and real MCP client / skill indexing.
    monkeypatch.setattr(c, "_create_llm", lambda _model=None: _DummyLLMPort())
    monkeypatch.setattr(
        FactoriesMixin,
        "_create_mcp_tool_retrieval_service",
        lambda _self, _registry: None,
    )
    monkeypatch.setattr(
        FactoriesMixin,
        "_create_mcp_client",
        lambda _self: None,
    )

    db_path = str(tmp_path / "sessions.db")
    c.configure_defaults(db_path=db_path, default_model="dummy")
    return c


class TestToolRegistrySharing:
    """The same RoleBasedToolRegistry instance must be shared across DI consumers."""

    def test_tool_registry_is_singleton(self, container):
        registry1 = container.get("tool_registry")
        registry2 = container.get("tool_registry")

        assert isinstance(registry1, RoleBasedToolRegistry)
        assert registry1 is registry2

    def test_mcp_bridge_uses_shared_tool_registry(self, container):
        registry = container.get("tool_registry")
        bridge = container._create_mcp_bridge()

        assert isinstance(bridge._registry, RoleBasedToolRegistry)
        assert bridge._registry is registry

    def test_plan_act_flow_factory_receives_shared_registry_and_bridge(
        self, container, monkeypatch,
    ):
        # Build a lightweight tool collection so PlanActFlow init does not
        # instantiate the full admin tool catalog.
        registry = container.get("tool_registry")
        registry.role_mappings = {"admin": []}
        tools = ToolCollection()
        monkeypatch.setattr(
            registry,
            "create_tool_collection",
            lambda *args, **kwargs: tools,
        )

        bridge = _DummyBridge()
        container.register_instance("mcp_bridge", bridge)

        session = Session(id="test-di")
        flow = container._build_plan_act_flow_for_session(session)

        assert flow._tool_registry is registry
        assert flow._mcp_bridge is bridge


class TestMcpToolRetrievalServiceFactory:
    """Feature-flag wiring for the scoped retrieval service."""

    def test_returns_none_when_scoped_aggregation_disabled(self, monkeypatch):
        class _SettingsOff:
            mcp_scoped_aggregation = False

        monkeypatch.setattr(
            "weebot.config.settings.WeebotSettings",
            _SettingsOff,
        )
        c = Container()
        result = c._create_mcp_tool_retrieval_service(None)
        assert result is None

    def test_returns_service_when_scoped_aggregation_enabled(self, monkeypatch):
        class _SettingsOn:
            mcp_scoped_aggregation = True

        monkeypatch.setattr(
            "weebot.config.settings.WeebotSettings",
            _SettingsOn,
        )
        c = Container()
        registry = RoleBasedToolRegistry()
        service = c._create_mcp_tool_retrieval_service(registry)

        assert isinstance(service, McpToolRetrievalService)
        assert service._k == MCP_DEFAULT_SCOPE_K
