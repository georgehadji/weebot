"""Dependency Injection container for weebot.

Centralizes port → adapter bindings so that the wiring lives in one
place rather than scattered across AgentRunner, factories, and web entry
points.

Factory methods extracted to ``di/_factories.py`` (23 methods).
Capability bindings extracted to ``di/_capabilities.py``,
``di/_agent_tools.py``, ``di/_skills.py``, ``di/_skillopt.py``.

Usage:
    container = Container()
    container.configure_defaults()
    runner = container.build_agent_runner(role="admin")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

from weebot.application.cqrs.behaviors.save_policy import SavePolicyBehavior
from weebot.application.cqrs.handlers import register_default_handlers
from weebot.application.cqrs.behaviors.logging import LoggingBehavior
from weebot.application.cqrs.behaviors.telemetry import TelemetryBehavior
from weebot.application.cqrs.mediator import Mediator
from weebot.application.ports.audit_port import AuditPort
from weebot.application.ports.backend_port import BackendPort
from weebot.application.ports.config_port import ConfigPort
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.event_store_port import EventStorePort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.memory_port import MemoryPort
from weebot.application.ports.metrics_port import MetricsPort
from weebot.application.ports.sandbox_port import SandboxPort
from weebot.application.ports.speech_port import SpeechPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.ports.steering_port import SteeringPort
from weebot.application.ports.task_router_port import TaskRouterPort
from weebot.application.ports.tool_repository_port import ToolRepositoryPort
from weebot.application.ports.swarm_event_bus_port import SwarmEventBusPort
from weebot.application.ports.sub_agent_cost_tracker_port import SubAgentCostTrackerPort
from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort
from weebot.application.ports.tracing_port import TracingPort
from weebot.application.ports.rerank_port import RerankPort
from weebot.infrastructure.adapters.sub_agent_cost_tracker import SubAgentCostTracker
from weebot.application.services.task_runner import TaskRunner
from weebot.config.harness.schema import HarnessConfig
from weebot.domain.ports import EventPublisher

from weebot.application.di._factories import FactoriesMixin
from weebot.application.di._agent_tools import AgentToolsMixin
from weebot.application.di._capabilities import CapabilitiesMixin
from weebot.application.di._skills import SkillsMixin
from weebot.application.di._skillopt import SkillOptMixin
from weebot.application.di._learning import LearningMixin


@dataclass
class Container(FactoriesMixin, AgentToolsMixin, CapabilitiesMixin,
                SkillsMixin, SkillOptMixin, LearningMixin):
    """Simple service-locator / DI container.

    Bindings are Callable factories (lazy) to avoid instantiating
    adapters that may never be used in a given process (e.g. browser
    in a CLI-only context).

    Factory methods live in ``di/_factories.py`` via ``FactoriesMixin``.
    Capability bindings live in ``di/_capabilities.py``, ``_agent_tools.py``,
    ``_skills.py``, and ``_skillopt.py``.
    """

    _bindings: dict[type, Callable[[], Any]] = field(default_factory=dict)
    _singletons: dict[type, Any] = field(default_factory=dict)

    # ── registration ────────────────────────────────────────────────

    def register(self, port_type: type, factory: Callable[[], Any]) -> None:
        """Register a lazy factory for *port_type*."""
        self._bindings[port_type] = factory

    def register_instance(self, port_type: type, instance: Any) -> None:
        """Register an already-created singleton."""
        self._singletons[port_type] = instance

    # ── resolution ──────────────────────────────────────────────────

    def get(self, port_type: type) -> Any:
        """Resolve *port_type*, creating it once (singleton per type)."""
        if port_type in self._singletons:
            return self._singletons[port_type]

        factory = self._bindings.get(port_type)
        if factory is None:
            name = port_type.__name__ if hasattr(port_type, "__name__") else str(port_type)
            raise KeyError(f"No binding registered for {name}")

        instance = factory()
        self._singletons[port_type] = instance
        return instance

    # ── convenience binders ─────────────────────────────────────────

    def configure_defaults(
        self, *, db_path="./weebot_sessions.db", default_model=None,
    ) -> None:
        """Wire all defaults: LLM → OpenRouter, state → SQLite, etc."""
        self.register(StateRepositoryPort, lambda: self._create_state_repo(db_path))
        self.register("session_persistence", lambda: self._create_session_persistence_adapter())
        self.register(EventBusPort, self._create_event_bus)
        self.register(TracingPort, self._create_tracing)
        self.register(EventPublisher, self._create_event_bridge)
        self.register(LLMPort, lambda: self._create_llm(default_model))
        self.register(SandboxPort, self._create_sandbox)
        self.register("activity_stream", lambda: self._create_activity_stream())
        self.register("response_cache", lambda: self._create_response_cache())
        self.register(Mediator, self._create_mediator)
        self.register(TaskRunner, self._create_task_runner)
        self.register(SteeringPort, self._create_steering)
        self.register(HarnessConfig, self._create_harness_config)
        self.register(TaskRouterPort, self._create_task_router)
        self.register("personality", self._create_personality)
        self.register("structured_logger", lambda: self._create_structured_logger())
        self.register(AuditPort, lambda: self._create_audit_service())
        self.register(MemoryPort, lambda: self._create_memory_adapter())
        self.register(ConfigPort, lambda: self._create_config_adapter())
        self.register(SpeechPort, lambda: self._create_speech())
        self.register(EventStorePort, lambda: self._create_event_store())
        self.register(ToolRepositoryPort, lambda: self._create_tool_repo())
        self.register(SwarmEventBusPort, self._create_swarm_bus)
        self.register(SubAgentFactoryPort, self._create_sub_agent_factory)
        self.register(SubAgentCostTrackerPort, lambda: SubAgentCostTracker(budget_usd=0.50))
        self.register("cascade_tracker", lambda: self._create_cascade_tracker())
        self.register("soul_provider", lambda: self._create_soul_provider())
        self.register(RerankPort, lambda: self._create_rerank_adapter())
        self.register("skill_retriever", lambda: self._create_skill_retriever())
        self.register("code_reviewer", self._create_code_reviewer)
        self.register("dreamer_agent", self._create_dreamer_agent)
        self.register("intent_review", self._create_intent_review_service)
        self.register("main_review", self._create_main_review_service)
        self.register("idea_gate", self._create_idea_gate)
        self.register("trust_report_service", self._create_trust_report_service)
        self.register("retention_agent", self._create_retention_agent)
        self.register(BackendPort, self._create_backend)
        self.register(MetricsPort, self._create_metrics_port)
        # Scheduler — APScheduler singleton, started/stopped via FastAPI lifespan
        from weebot.scheduling.scheduler import SchedulingManager
        self.register("scheduler", lambda: SchedulingManager())

        # MCP Client — connects to external MCP servers (Track 1)
        self.register("mcp_client", self._create_mcp_client)
        self.register("mcp_bridge", self._create_mcp_bridge)
        # Deployment-time learning (Memento-Skills; all flags default OFF)
        self.configure_learning(db_path=db_path)

    # ── high-level builders ─────────────────────────────────────────

    def build_scheduler(self) -> "SchedulingManager":
        """Return the DI-managed SchedulingManager singleton."""
        from weebot.scheduling.scheduler import SchedulingManager
        return self.get("scheduler")

    def build_agent_runner(self, role="admin", mcp_config=None, use_rich=True):
        """Construct a ready-to-use AgentRunner."""
        from weebot.interfaces.cli.agent_runner import AgentRunner
        return AgentRunner(
            llm=self.get(LLMPort),
            state_repo=self.get(StateRepositoryPort),
            event_bus=self.get(EventBusPort),
            model=self._maybe_get_model(),
            role=role, mcp_config=mcp_config, use_rich=use_rich,
            mediator=self._maybe_get(Mediator),
        )

    def build_mediator(self) -> Mediator:
        """Build a configured Mediator with default handlers registered."""
        mediator = Mediator()
        mediator.add_pipeline_behavior(LoggingBehavior())
        mediator.add_pipeline_behavior(TelemetryBehavior())
        mediator.add_pipeline_behavior(
            SavePolicyBehavior(state_repo=self._maybe_get(StateRepositoryPort))
        )
        state_repo = self.get(StateRepositoryPort)
        task_runner = self._maybe_get(TaskRunner)
        llm = self._maybe_get(LLMPort)
        event_bus = self._maybe_get(EventBusPort)
        tools = None
        if llm is not None:
            from weebot.application.models.tool_collection import ToolCollection
            from weebot.tools.bash_tool import BashTool
            from weebot.tools.file_editor import StrReplaceEditorTool as FileEditorTool
            from weebot.tools.python_tool import PythonExecuteTool as PythonTool
            from weebot.tools.image_gen_tool import ImageGenTool
            try:
                sandbox = self._maybe_get(SandboxPort)
                py_tool = PythonTool(sandbox=sandbox) if sandbox else PythonTool()
                tools = ToolCollection(BashTool(), FileEditorTool(), py_tool, ImageGenTool())
            except Exception:
                tools = None
        scoring_port = self._maybe_get_str("scoring_port")
        trajectory_builder = self._maybe_get_str("trajectory_builder")
        register_default_handlers(
            mediator, state_repo, task_runner,
            llm=llm, tools=tools, event_bus=event_bus,
            scoring_port=scoring_port, trajectory_builder=trajectory_builder,
        )
        return mediator

    def build_chat_flow(self, session, model=None):
        """Construct a ChatFlow for conversational sessions."""
        from weebot.application.flows.chat_flow import ChatFlow
        return ChatFlow(
            llm=self.get(LLMPort), session=session,
            event_bus=self.get(EventBusPort), model=model,
            mediator=self._maybe_get(Mediator),
            state_repo=self.get(StateRepositoryPort),
        )

    # ── internal helpers ───────────────────────────────────────────

    def _maybe_get(self, port_type: type) -> Optional[Any]:
        """Return registered instance or None if not bound."""
        try:
            return self.get(port_type)
        except KeyError:
            return None

    def _maybe_get_str(self, key: str) -> Optional[Any]:
        """Return string-keyed registered instance or None if not bound."""
        try:
            return self.get(key)
        except KeyError:
            return None

    def _create_session_persistence_adapter(self):
        """Create a SessionPersistenceAdapter wrapping the StateRepositoryPort."""
        from weebot.infrastructure.persistence.session_persistence_adapter import (
            SessionPersistenceAdapter,
        )
        from weebot.utils.backoff import RetryWithBackoff, BackoffConfig

        retry = RetryWithBackoff(
            BackoffConfig(delays=[0.5, 1.0, 2.0], jitter=0.25)
        )
        return SessionPersistenceAdapter(
            repo=self.get(StateRepositoryPort),
            retry=retry,
        )

    def _create_swarm_bus(self):
        """Create a SwarmEventBus."""
        from weebot.infrastructure.swarm_event_bus import SwarmEventBus
        return SwarmEventBus()

    def _create_sub_agent_factory(self):
        """Create a SubAgentFactory."""
        from weebot.infrastructure.adapters.sub_agent_factory import SubAgentFactory
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.application.models.tool_collection import ToolCollection
        from weebot.tools.bash_tool import BashTool
        from weebot.tools.file_editor import StrReplaceEditorTool as FileEditorTool
        from weebot.tools.python_tool import PythonExecuteTool as PythonTool
        from weebot.tools.image_gen_tool import ImageGenTool

        sandbox = self._maybe_get(SandboxPort)
        py_tool = PythonTool(sandbox=sandbox) if sandbox else PythonTool()
        tools = ToolCollection(
            BashTool(),
            FileEditorTool(),
            py_tool,
            ImageGenTool(),
        )

        from weebot.config.model_refs import MODEL_CASCADE_TIER2, MODEL_CASCADE_TIER4, MODEL_ROLE_CODER
        from weebot.domain.models.sub_agent import AgentTier
        _TIER_MODEL: dict[AgentTier, str] = {
            AgentTier.BUDGET: MODEL_CASCADE_TIER2,
            AgentTier.STANDARD: MODEL_ROLE_CODER,
            AgentTier.PREMIUM: MODEL_CASCADE_TIER4,
        }

        def _build_sub_flow(session, spec, llm, tools):
            mediator = self.build_mediator()
            return PlanActFlow(
                llm=llm,
                tools=tools,
                session=session,
                event_bus=None,
                model=spec.model or _TIER_MODEL.get(spec.tier, MODEL_CASCADE_TIER2),
                mediator=mediator,
                state_repo=self._maybe_get("state_repo_port"),
                skill_prompt=None,
                max_steps=spec.max_tool_calls,
            )

        return SubAgentFactory(
            llm=self.get(LLMPort),
            tools=tools,
            cost_tracker=self.get(SubAgentCostTrackerPort),
            swarm_bus=self._maybe_get(SwarmEventBusPort),
            flow_factory=_build_sub_flow,
        )

    def build_hyper_agent_flow(self, session, model=None):
        """Construct a HyperAgentFlow for multi-agent task execution."""
        from weebot.application.flows.hyper_agent_flow import HyperAgentFlow

        return HyperAgentFlow(
            llm=self.get(LLMPort),
            session=session,
            event_bus=self.get(EventBusPort),
            swarm_bus=self.get(SwarmEventBusPort),
            sub_agent_factory=self.get(SubAgentFactoryPort),
            cost_tracker=self.get(SubAgentCostTrackerPort),
            model=model or self._maybe_get_model(),
            mediator=self._maybe_get(Mediator),
        )

    def _maybe_get_model(self) -> Optional[str]:
        """Return the default model string if LLM is bound."""
        return getattr(self, "_default_model", None)

    # ── startup validation ─────────────────────────────────────────

    def validate(self) -> list[str]:
        """Resolve every registered binding to catch misconfiguration early."""
        errors: list[str] = []
        for port_type in list(self._bindings.keys()):
            if isinstance(port_type, str):
                continue
            try:
                self.get(port_type)
            except Exception as exc:
                name = port_type.__name__ if hasattr(port_type, "__name__") else str(port_type)
                errors.append(f"{name}: {exc}")
        return errors
