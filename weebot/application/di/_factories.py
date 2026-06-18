"""Factory method mixin for Container — extracted from di.py.

Contains the 23 @staticmethod / instance factory methods that create adapters.
"""
from __future__ import annotations

import os as _os
from typing import Any, Optional

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.event_store_port import EventStorePort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.sandbox_port import SandboxPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.ports.steering_port import SteeringPort
from weebot.application.ports.task_router_port import TaskRouterPort
from weebot.config.harness.schema import HarnessConfig
from weebot.config.model_refs import MODEL_DI_DEFAULT


class FactoriesMixin:
    """Factory methods extracted from Container."""

    @staticmethod
    def _create_state_repo(db_path: str) -> StateRepositoryPort:
        if _os.environ.get("WEEBOT_DB_BACKEND", "").lower() == "postgresql":
            from weebot.infrastructure.persistence.postgresql.state_repo import (
                PostgreSQLStateRepository,
            )
            return PostgreSQLStateRepository()
        from weebot.infrastructure.persistence.sqlite_state_repo import (
            SQLiteStateRepository,
        )
        return SQLiteStateRepository(db_path=db_path)

    @staticmethod
    def _create_event_bus() -> EventBusPort:
        from weebot.infrastructure.event_bus import AsyncEventBus
        return AsyncEventBus()

    @staticmethod
    def _create_tracing():
        from weebot.infrastructure.observability.tracing_adapter import TracingAdapter
        return TracingAdapter()

    def _create_event_bridge(self):
        from weebot.infrastructure.events.broker_adapter import EventBrokerAdapter
        from weebot.application.ports.event_bus_port import EventBusPort
        return EventBrokerAdapter(event_bus=self.get(EventBusPort))

    @staticmethod
    def _create_activity_stream():
        from weebot.core.activity_stream import ActivityStream
        return ActivityStream()

    @staticmethod
    def _create_tool_repo():
        from weebot.infrastructure.persistence.sqlite_tool_repo import (
            SQLiteToolRepository,
        )
        return SQLiteToolRepository()

    @staticmethod
    def _create_structured_logger():
        from weebot.core.structured_logger import StructuredLogger
        return StructuredLogger("weebot")

    @staticmethod
    def _create_config_adapter():
        from weebot.infrastructure.adapters.config_adapter import ConfigAdapter
        return ConfigAdapter()

    @staticmethod
    def _create_audit_service():
        from weebot.application.services.audit_service import AuditService
        return AuditService()

    @staticmethod
    def _create_memory_adapter():
        from weebot.infrastructure.persistence.filesystem_memory import (
            FileSystemMemoryAdapter,
        )
        return FileSystemMemoryAdapter()

    @staticmethod
    def _create_speech():
        from weebot.infrastructure.adapters.speech.whisper_adapter import (
            WhisperSpeechAdapter,
        )
        return WhisperSpeechAdapter()

    @staticmethod
    def _create_event_store():
        from weebot.infrastructure.event_store import EventStore
        return EventStore()

    @staticmethod
    def _create_response_cache():
        from weebot.infrastructure.persistence.response_cache import ResponseCache
        return ResponseCache()

    @staticmethod
    def _create_sandbox() -> SandboxPort:
        from weebot.infrastructure.sandbox.factory import create_default_sandbox
        return create_default_sandbox()

    @staticmethod
    def _create_llm(default_model: Optional[str]) -> LLMPort:
        from weebot.infrastructure.adapters.llm.adapter_factory import create_adapter
        from weebot.config.model_registry import ModelProvider
        model = default_model or MODEL_DI_DEFAULT
        provider = ModelProvider.from_model_name(model).value
        return create_adapter(provider, model=model)

    def _create_mediator(self):
        return self.build_mediator()

    def _create_task_runner(self):
        from weebot.application.services.task_runner import TaskRunner
        from weebot.application.ports.state_repo_port import StateRepositoryPort
        from weebot.application.ports.event_bus_port import EventBusPort
        return TaskRunner(
            state_repo=self.get(StateRepositoryPort),
            event_bus=self.get(EventBusPort),
        )

    @staticmethod
    def _create_steering():
        from weebot.infrastructure.adapters.steering_adapter import InMemorySteeringAdapter
        return InMemorySteeringAdapter()

    @staticmethod
    def _create_task_router():
        from weebot.application.services.keyword_task_router import KeywordTaskRouter
        return KeywordTaskRouter()

    @staticmethod
    def _create_tool_discovery():
        from weebot.infrastructure.adapters.tool_discovery import ToolDiscoveryAdapter
        return ToolDiscoveryAdapter()

    @staticmethod
    def _create_cascade_tracker():
        from weebot.core.model_cascade_tracker import ModelCascadeTracker
        return ModelCascadeTracker()

    @staticmethod
    def _create_rerank_adapter():
        from weebot.infrastructure.adapters.openrouter_rerank_adapter import (
            OpenRouterRerankAdapter,
        )
        return OpenRouterRerankAdapter()

    @staticmethod
    def _create_checkpoint_store(db_path: str = "sessions.db"):
        from weebot.infrastructure.persistence.checkpoint_store import SQLiteCheckpointStore
        return SQLiteCheckpointStore(db_path=db_path)

    @staticmethod
    def _create_flow_serializer():
        from weebot.application.services.flow_serializer import FlowSerializer
        return FlowSerializer()

    def _create_personality(self):
        from weebot.core.personality_manager import PersonalityManager
        # Resolve SoulProviderPort from the same container instance
        soul = self._maybe_get_str("soul_provider")
        return PersonalityManager(soul_provider=soul)

    @staticmethod
    def _create_soul_provider():
        from weebot.infrastructure.adapters.soul_provider import FileSystemSoulProvider
        return FileSystemSoulProvider()

    @staticmethod
    def _create_llm_for_role(role: str) -> "LLMPort":
        """Create an LLMPort for a specific role from ROLE_MODEL_CONFIG.

        Falls back to the default model if the role is not configured.
        """
        from weebot.core.model_cascade_config import ROLE_MODEL_CONFIG
        models = ROLE_MODEL_CONFIG.get(role, [])
        model = models[0] if models else None
        return FactoriesMixin._create_llm(model)

    @staticmethod
    def _create_intent_review_service() -> "IntentReviewService":
        from weebot.application.services.intent_review_service import IntentReviewService
        llm = FactoriesMixin._create_llm_for_role("critic")
        return IntentReviewService(llm=llm)

    @staticmethod
    def _create_main_review_service() -> "MainReviewService":
        from weebot.application.services.main_review_service import MainReviewService
        llm = FactoriesMixin._create_llm_for_role("verifier")
        return MainReviewService(llm=llm)

    @staticmethod
    def _create_idea_gate() -> "IdeaGate":
        from weebot.application.services.idea_gate import IdeaGate
        from weebot.application.services.intent_review_service import IntentReviewService
        from weebot.application.services.main_review_service import MainReviewService
        critic_llm = FactoriesMixin._create_llm_for_role("critic")
        verifier_llm = FactoriesMixin._create_llm_for_role("verifier")
        intent_reviewer = IntentReviewService(llm=critic_llm)
        main_reviewer = MainReviewService(llm=verifier_llm)
        return IdeaGate(intent_reviewer=intent_reviewer, main_reviewer=main_reviewer)

    @staticmethod
    def _create_dreamer_agent() -> "DreamerAgent":
        from weebot.application.agents.dreamer import DreamerAgent
        llm = FactoriesMixin._create_llm_for_role("dreamer")
        return DreamerAgent(llm=llm, max_contracts=5)

    @staticmethod
    def _create_code_reviewer() -> "CodeReviewerService":
        from weebot.application.services.code_reviewer_service import CodeReviewerService
        from weebot.application.di._factories import FactoriesMixin
        llm = FactoriesMixin._create_llm_for_role("reviewer")
        return CodeReviewerService(llm=llm, timeout_seconds=8.0)

    @staticmethod
    def _create_retention_agent() -> "RetentionAgent":
        from weebot.application.agents.retention_agent import RetentionAgent
        llm = FactoriesMixin._create_llm_for_role("subagent")
        return RetentionAgent(llm=llm)

    @staticmethod
    def _create_trust_report_service() -> "TrustReportService":
        from weebot.application.services.trust_report_service import TrustReportService
        return TrustReportService()

    @staticmethod
    def _create_backend():
        from weebot.infrastructure.adapters.sandbox_backend_adapter import SandboxBackendAdapter
        from weebot.application.di import Container
        try:
            c = Container()
            c.configure_defaults()
            sandbox = c.get(SandboxPort)
            return SandboxBackendAdapter(sandbox=sandbox)
        except Exception:
            return SandboxBackendAdapter(sandbox=None)

    @staticmethod
    def _create_harness_config():
        from pathlib import Path
        version = _os.getenv("WEEBOT_HARNESS_VERSION", "v0.2.0")
        config_path = (
            Path(__file__).resolve().parent.parent.parent
            / "config" / "harness" / f"{version}.yaml"
        )
        if config_path.exists():
            return HarnessConfig.load(str(config_path))
        return HarnessConfig.default()

    @staticmethod
    def _create_metrics_port():
        """Create a MetricsPort (PrometheusMetricsAdapter)."""
        from weebot.infrastructure.observability.prometheus_adapter import (
            PrometheusMetricsAdapter,
        )
        return PrometheusMetricsAdapter()

    @staticmethod
    def _create_egress_guard():
        """Create an EgressGuard singleton, managed by the DI container."""
        from weebot.core.egress_guard import EgressGuard
        return EgressGuard()

    # ── MCP Client factories (Track 1 — Hermes Audit) ─────────────

    def _create_mcp_client(self):
        """Create an MCPClientManager from config.

        Reads server configurations from the configured config path.
        Returns an empty (no-op) manager if no servers are configured.
        """
        from weebot.infrastructure.mcp.mcp_client_manager import MCPClientManager

        # Try to load server configs from WeebotSettings
        try:
            from weebot.config.settings import WeebotSettings
            settings = WeebotSettings()
            config_path = settings.mcp_servers_config_path
            if config_path:
                import json, yaml
                from pathlib import Path
                path = Path(config_path)
                if path.exists():
                    raw = path.read_text(encoding="utf-8")
                    if config_path.endswith((".yaml", ".yml")):
                        servers = yaml.safe_load(raw)
                    else:
                        servers = json.loads(raw)
                    return MCPClientManager(config={"mcpServers": servers})
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to load MCP config from settings: %s", exc
            )

        return MCPClientManager(config={})

    def _create_mcp_bridge(self):
        """Create an MCPToolRegistryBridge with the MCP client injected."""
        from weebot.application.services.mcp_tool_registry_bridge import (
            MCPToolRegistryBridge,
        )
        from weebot.tools.tool_registry import RoleBasedToolRegistry

        client = self._maybe_get_str("mcp_client")
        registry = RoleBasedToolRegistry()
        bridge = MCPToolRegistryBridge(
            mcp_client=client,
            registry=registry,
        )
        return bridge

    def build_mcp_bridge(self) -> "MCPToolRegistryBridge":
        """Build and initialize the MCP bridge singleton."""
        from weebot.application.services.mcp_tool_registry_bridge import (
            MCPToolRegistryBridge,
        )
        bridge = self._maybe_get_str("mcp_bridge")
        if bridge is None:
            bridge = self._create_mcp_bridge()
            self.register_instance("mcp_bridge", bridge)
        return bridge
