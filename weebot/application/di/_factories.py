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
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()
        if settings.sandbox_mode != "auto":
            from weebot.infrastructure.sandbox.factory import SandboxFactory, MODE_TO_TYPE
            sandbox_type = MODE_TO_TYPE.get(settings.sandbox_mode.lower())
            if sandbox_type is None:
                raise ValueError(
                    f"Unknown sandbox_mode '{settings.sandbox_mode}'. "
                    f"Set SANDBOX_MODE to: auto, native, docker, wsl2."
                )
            return SandboxFactory().create(sandbox_type)
        import sys as _sys
        if _sys.platform == "win32":
            from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox
            return NativeWindowsSandbox()
        from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox
        return DockerLinuxSandbox()

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
    def _create_checkpoint_store(db_path: str = "sessions.db"):
        from weebot.infrastructure.persistence.checkpoint_store import SQLiteCheckpointStore
        return SQLiteCheckpointStore(db_path=db_path)

    @staticmethod
    def _create_flow_serializer():
        from weebot.application.services.flow_serializer import FlowSerializer
        return FlowSerializer()

    @staticmethod
    def _create_personality():
        from weebot.core.personality_manager import PersonalityManager
        return PersonalityManager()

    @staticmethod
    def _create_harness_config():
        from pathlib import Path
        version = _os.getenv("WEEBOT_HARNESS_VERSION", "v0.1.0")
        config_path = (
            Path(__file__).resolve().parent.parent.parent
            / "config" / "harness" / f"{version}.yaml"
        )
        if config_path.exists():
            return HarnessConfig.load(str(config_path))
        return HarnessConfig.default()
