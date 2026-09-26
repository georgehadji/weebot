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
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

from weebot.application.cqrs.behaviors.save_policy import SavePolicyBehavior  # noqa: E402
from weebot.application.cqrs.handlers import register_default_handlers  # noqa: E402
from weebot.application.cqrs.behaviors.logging import LoggingBehavior  # noqa: E402
from weebot.application.cqrs.behaviors.telemetry import TelemetryBehavior  # noqa: E402
from weebot.application.cqrs.mediator import Mediator  # noqa: E402
from weebot.application.ports.event_bus_port import EventBusPort  # noqa: E402
from weebot.application.ports.event_store_port import EventStorePort  # noqa: E402
from weebot.application.ports.gateway_session_store_port import (  # noqa: E402
    IGatewaySessionStorePort,
)
from weebot.application.ports.llm_port import LLMPort  # noqa: E402
from weebot.application.ports.provider_account_port import ProviderAccountPort  # noqa: E402
from weebot.application.ports.sandbox_port import SandboxPort  # noqa: E402
from weebot.application.ports.speech_port import SpeechPort  # noqa: E402
from weebot.application.ports.state_repo_port import StateRepositoryPort  # noqa: E402
from weebot.application.ports.steering_port import SteeringPort  # noqa: E402
from weebot.application.ports.task_queue_port import TaskQueuePort  # noqa: E402
from weebot.application.ports.task_runner_port import TaskRunnerPort  # noqa: E402
from weebot.application.ports.tool_repository_port import ToolRepositoryPort  # noqa: E402
from weebot.application.ports.swarm_event_bus_port import SwarmEventBusPort  # noqa: E402
from weebot.application.ports.sub_agent_cost_tracker_port import (  # noqa: E402
    SubAgentCostTrackerPort,
)
from weebot.application.ports.sub_agent_factory_port import SubAgentFactoryPort  # noqa: E402
from weebot.application.ports.rerank_port import RerankPort  # noqa: E402
from weebot.application.services.task_runner import TaskRunner  # noqa: E402
from weebot.config.harness.schema import HarnessConfig  # noqa: E402

from weebot.application.di._factories import FactoriesMixin  # noqa: E402
from weebot.application.di._agent_tools import AgentToolsMixin  # noqa: E402
from weebot.application.di._capabilities import CapabilitiesMixin  # noqa: E402


def _lazy_cost_tracker():
    """Lazy-import SubAgentCostTracker to avoid top-level infra import."""
    from weebot.infrastructure.adapters.sub_agent_cost_tracker import SubAgentCostTracker

    return SubAgentCostTracker(budget_usd=0.50)


from weebot.application.di._skills import SkillsMixin  # noqa: E402
from weebot.application.di._skillopt import SkillOptMixin  # noqa: E402
from weebot.application.di._learning import LearningMixin  # noqa: E402


@dataclass
class Container(
    FactoriesMixin, AgentToolsMixin, CapabilitiesMixin, SkillsMixin, SkillOptMixin, LearningMixin
):
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

    def warm_up(self) -> None:
        """Build now what the first flow would otherwise build mid-request.

        The Mediator is required by every flow (PlanningState and
        ExecutingState refuse to run without one) and constructing it builds
        the role LLM adapters and the tool registry -- tens of seconds on a
        cold start. The web server calls this at startup so that cost is not
        paid inside the first user's request.
        """
        self.get(Mediator)

    # ── convenience binders ─────────────────────────────────────────

    def configure_defaults(self, *, db_path="./weebot_sessions.db", default_model=None) -> None:
        """Wire all defaults: LLM → OpenRouter, state → SQLite, etc."""
        self.register(StateRepositoryPort, lambda: self._create_state_repo(db_path))
        self.register("session_persistence", lambda: self._create_session_persistence_adapter())
        self.register(EventBusPort, self._create_event_bus)
        from weebot.infrastructure.observability.tracing_adapter import TracingAdapter

        self.register(TracingAdapter, self._create_tracing)
        self.register(LLMPort, lambda: self._create_llm(default_model))
        self.register(SandboxPort, self._create_sandbox)
        self.register(Mediator, self._create_mediator)
        self.register(TaskQueuePort, self._create_task_queue)
        self.register(TaskRunner, self._create_task_runner)
        # TaskRunnerPort resolves to the same TaskRunner singleton — it exists
        # so interfaces/ can depend on the narrow structural type instead of
        # the concrete class (see task_runner_port.py docstring for why).
        self.register(TaskRunnerPort, lambda: self.get(TaskRunner))
        # Registered under the port, not the concrete adapter class, so
        # callers depend on the abstraction (DIP) — matches every other
        # port binding in this method.
        self.register(SteeringPort, self._create_steering)
        self.register(HarnessConfig, self._create_harness_config)
        self.register("personality", self._create_personality)
        self.register("structured_logger", lambda: self._create_structured_logger())
        from weebot.application.services.audit_service import AuditService

        self.register(AuditService, lambda: self._create_audit_service())
        from weebot.infrastructure.persistence.filesystem_memory import FileSystemMemoryAdapter

        self.register(FileSystemMemoryAdapter, lambda: self._create_memory_adapter())
        self.register(SpeechPort, lambda: self._create_speech())
        self.register(EventStorePort, lambda: self._create_event_store())
        # The Telegram gateway's session store. Resolved here -- not built by
        # web/main.py -- so session deletion purges the same store it writes.
        self.register(IGatewaySessionStorePort, self._create_gateway_session_store)
        self.register(ToolRepositoryPort, lambda: self._create_tool_repo())
        self.register(SwarmEventBusPort, self._create_swarm_bus)
        self.register(SubAgentFactoryPort, self._create_sub_agent_factory)
        self.register(SubAgentCostTrackerPort, lambda: _lazy_cost_tracker())
        self.register("cascade_tracker", lambda: self._create_cascade_tracker())
        self.register("soul_provider", lambda: self._create_soul_provider())
        self.register(RerankPort, lambda: self._create_rerank_adapter())
        self.register("skill_retriever", lambda: self._create_skill_retriever())
        self.register("code_reviewer", self._create_code_reviewer)
        self.register("dreamer_agent", self._create_dreamer_agent)
        self.register("idea_gate", self._create_idea_gate)
        self.register("retention_agent", self._create_retention_agent)
        from weebot.application.ports.file_storage_port import FileStoragePort

        self.register(FileStoragePort, lambda: self._create_file_storage())
        self.register("step_audit_service", self._create_step_evidence_auditor)
        # LongHorizon-Harness E6: verifier calls on the cheap ROLE_MODEL_CONFIG
        # tier instead of the flow's (usually pricier) default model. Falls
        # back to that default automatically if role config is absent.
        self.register("verifier_llm", lambda: self._create_llm_for_role("verifier"))
        # LongHorizon-Harness E7b: integrity axis — detect the verifier
        # writing to the workspace it is supposed to only observe.
        self.register("workspace_snapshots", self._create_workspace_snapshots)

        # Live-session trajectory scoring. CompletedState sends
        # ScoreTrajectoryCommand after every flow, and until now nothing in the
        # main container could handle it: the scorer was looked up under a
        # string nobody registered, the builder and repository were registered
        # only inside configure_skillopt(), and the handler persisted to a
        # store no learner reads. The scorer is PlanOutcomeScorer -- the other
        # three ScoringPort implementations compare against an expected answer
        # a live session does not have, so each would produce a constant,
        # meaningless score. Cost per completed session: one trajectory-summary
        # call, on the cheap verifier tier. The score itself is free.
        from weebot.application.ports.scoring_port import ScoringPort

        def _create_plan_outcome_scorer():
            from weebot.infrastructure.scoring.plan_outcome_scorer import PlanOutcomeScorer

            return PlanOutcomeScorer()

        def _create_trajectory_builder():
            from weebot.application.services.trajectory_builder import TrajectoryBuilder

            return TrajectoryBuilder(llm=self.get("verifier_llm"))

        self.register(ScoringPort, _create_plan_outcome_scorer)
        self.register("trajectory_builder", _create_trajectory_builder)
        self.register("trajectory_repo", lambda: self._create_trajectory_repo(db_path))
        from weebot.infrastructure.observability.prometheus_adapter import PrometheusMetricsAdapter

        self.register(PrometheusMetricsAdapter, self._create_metrics_port)
        # Scheduler — APScheduler singleton, started/stopped via FastAPI lifespan
        from weebot.scheduling.scheduler import SchedulingManager

        self.register("scheduler", lambda: SchedulingManager())

        # Flow registry — breaks services/flows circular dependency
        from weebot.application.abstractions import FlowRegistry

        self.register("flow_registry", lambda: FlowRegistry())
        # Populate the registry with known flow types
        self.build_flow_registry()

        # Flow factory callable — resolved here so application services can
        # receive it by injection instead of importing the interfaces layer.
        # The composition root owns cross-layer imports; services must not.
        #
        # It hands out a builder that fills in the collaborators every flow
        # REQUIRES from this container, rather than the bare create_flow.
        # Handing out the bare function left each caller to remember the
        # mediator, and two did not: TaskRunner.create_plan_act_factory -- the
        # only way the web API starts a task -- and CronAgentRunner. Since
        # 2b6f679 (2026-06-06) PlanningState refuses to run without a
        # mediator, so every web-started session and every cron agent job
        # emitted "PlanningState requires a Mediator" and planned nothing,
        # while the CLI, which passes one, worked. The tests mocked the factory
        # on both web paths, which is how it stayed green.
        #
        # Resolved when a flow is BUILT, not when the builder is: the Mediator's
        # own factory resolves TaskRunner, and TaskRunner holds this builder,
        # so resolving the Mediator eagerly here would recurse. Explicit
        # arguments still win; a None mediator is never kept, because no flow
        # can run on one.
        def _create_flow_callable():
            from weebot.interfaces.factories import create_flow

            def _build_flow(**kwargs):
                if kwargs.get("mediator") is None:
                    kwargs["mediator"] = self.get(Mediator)
                if kwargs.get("state_repo") is None:
                    kwargs["state_repo"] = self.get(StateRepositoryPort)
                return create_flow(**kwargs)

            return _build_flow

        self.register("create_flow", _create_flow_callable)

        # Action Canonicalizer factory (Tier 1.1) — resolved here so the
        # interfaces layer can build one per tool list without importing
        # infrastructure adapters directly (composition root owns that import).
        def _build_action_canonicalizer(tools):
            from weebot.infrastructure.adapters.action_canonicalizer import ActionCanonicalizer

            cfg = self.get(HarnessConfig).canonicalizer
            return ActionCanonicalizer(
                tools=tools, strict_mode=cfg.strict_mode, coerce_types=cfg.coerce_types
            )

        self.register("build_action_canonicalizer", lambda: _build_action_canonicalizer)

        # Environment Contract Layer (Tier 3.2) — loads config/contracts/*.yaml
        # once and hands back a ready ContractLoader. No per-tool-list
        # dependency (unlike the canonicalizer), so this is a plain singleton
        # rather than a factory-returning-a-factory.
        def _create_contract_loader():
            from weebot.infrastructure.adapters.contract_loader import ContractLoader

            contracts_dir = self.get(HarnessConfig).canonicalizer.contracts_dir
            return ContractLoader(contracts_dir=contracts_dir)

        self.register("contract_loader", _create_contract_loader)

        # ── Startup catalog validation (warnings only, never blocks) ──
        try:
            from weebot.config._catalog_validator import CatalogValidator

            _report = CatalogValidator.run_default_validation()
            _report.log_summary()
        except Exception as _exc:
            import logging as _logging

            _logging.getLogger("weebot.application.di").warning(
                "Catalog validation skipped: %s", _exc
            )
        # ─────────────────────────────────────────────────────────────

        # Egress guard — migrated from global singleton to DI
        from weebot.core.egress_guard import EgressGuard

        self.register(EgressGuard, self._create_egress_guard)

        # Global LLM concurrency pool — bounds parallel API calls (WP-8)
        def _create_llm_pool():
            from weebot.application.strategies.llm_pool import LLMPool
            from weebot.config.settings import WeebotSettings

            _settings = WeebotSettings()
            return LLMPool(
                max_concurrent=_settings.llm_max_concurrent_requests,
                acquire_timeout=_settings.llm_pool_acquire_timeout_s,
            )

        self.register("llm_pool", _create_llm_pool)

        # Credit balance + live model list for the cascade (phase 3.1). These
        # were raw httpx calls to openrouter.ai inside CascadeExecutor.
        def _create_provider_account():
            from weebot.config.settings import WeebotSettings
            from weebot.infrastructure.adapters.llm.openrouter_account import (
                OpenRouterAccountAdapter,
            )

            return OpenRouterAccountAdapter(api_key=WeebotSettings().openrouter_api_key)

        self.register(ProviderAccountPort, _create_provider_account)

        # Browser pool — DI-managed singleton replacing module-level _global_pool
        self.register("browser_pool", self._create_browser_pool)
        # MCP Client — connects to external MCP servers (Track 1)
        self.register("mcp_client", self._create_mcp_client)
        self.register("tool_registry", self._create_tool_registry)
        self.register("mcp_bridge", self._create_mcp_bridge)
        self.register("native_tool_selector", self._create_native_tool_selector)
        # Knowledge graph — lazy bindings; nothing touches the DB until used.
        self.configure_knowledge_graph(db_path=db_path)
        # Deployment-time learning (Memento-Skills; all flags default OFF)
        self.configure_learning(db_path=db_path)

    # ── high-level builders ─────────────────────────────────────────

    def build_flow_registry(self) -> FlowRegistry:  # noqa: F821
        """Build and populate the flow registry, then return it."""
        from weebot.application.abstractions import FlowRegistry  # noqa: F401
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.application.flows.chat_flow import ChatFlow
        from weebot.infrastructure.observability.tracing_adapter import TracingAdapter  # noqa: F401

        registry = self.get("flow_registry")

        # PlanActFlow — the primary agent flow
        registry.register(
            "plan_act",
            lambda **kw: PlanActFlow(
                llm=self.get(LLMPort),
                tools=kw.get("tools"),
                session=kw.get("session"),
                event_bus=(self.get(EventBusPort) if kw.get("event_bus") is not False else None),
                model=kw.get("model") or self._maybe_get_model(),
                mediator=self._maybe_get(Mediator),
                state_repo=self.get(StateRepositoryPort),
                skill_prompt=kw.get("skill_prompt"),
                tracing_port=(
                    self._maybe_get(TracingAdapter) if self._is_tracing_enabled() else None
                ),
                knowledge_graph=(
                    self._maybe_get_str("knowledge_graph")
                    if self._is_kg_extraction_enabled()
                    else None
                ),
            ),
        )

        # ChatFlow — lightweight conversational flow
        registry.register(
            "chat",
            lambda **kw: ChatFlow(
                llm=self.get(LLMPort),
                session=kw.get("session"),
                event_bus=(self.get(EventBusPort) if kw.get("event_bus") is not False else None),
                model=kw.get("model") or self._maybe_get_model(),
                mediator=self._maybe_get(Mediator),
                state_repo=self.get(StateRepositoryPort),
            ),
        )

        return registry

    def build_scheduler(self) -> SchedulingManager:  # noqa: F821
        """Return the DI-managed SchedulingManager singleton."""
        from weebot.scheduling.scheduler import SchedulingManager  # noqa: F401

        return self.get("scheduler")

    def build_agent_runner(self, role="admin", mcp_config=None, use_rich=True):
        """Construct a ready-to-use AgentRunner."""
        from weebot.interfaces.cli.agent_runner import AgentRunner

        return AgentRunner(
            llm=self.get(LLMPort),
            state_repo=self.get(StateRepositoryPort),
            event_bus=self.get(EventBusPort),
            model=self._maybe_get_model(),
            role=role,
            mcp_config=mcp_config,
            use_rich=use_rich,
            mediator=self._maybe_get(Mediator),
        )

    def build_mediator(self) -> Mediator:
        """Build a configured Mediator with default handlers registered."""
        from weebot.application.cqrs.behaviors.validation import ValidationBehavior

        mediator = Mediator()
        mediator.add_pipeline_behavior(ValidationBehavior())
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
            from weebot.tools.tool_registry import RoleBasedToolRegistry

            try:
                sandbox = self._maybe_get(SandboxPort)
                registry = RoleBasedToolRegistry()

                def _flow_factory(s):
                    return self._build_plan_act_flow_for_session(s)

                tools = registry.create_tool_collection(
                    role="admin", sandbox_port=sandbox, llm_port=llm, flow_factory=_flow_factory
                )
            except Exception as exc:
                # Do not fail silently: "no tools configured" and "tool
                # construction blew up" are indistinguishable downstream, and
                # the latter silently disables all agent tool use.
                logger.warning(
                    "Tool collection construction failed — agent will run " "tool-less: %s",
                    exc,
                    exc_info=True,
                )
                tools = None
        # Resolved by TYPE. This was `_maybe_get_str("scoring_port")`, a string
        # nothing registered: _maybe_get_str swallowed the KeyError, returned
        # None, and ScoreTrajectoryHandler was never registered -- so the
        # ScoreTrajectoryCommand CompletedState sends after every flow failed
        # and was logged as a warning, every time.
        from weebot.application.ports.scoring_port import ScoringPort

        scoring_port = self._maybe_get(ScoringPort)
        trajectory_builder = self._maybe_get_str("trajectory_builder")
        trajectory_repo = self._maybe_get_str("trajectory_repo")

        # ExecuteStepCommand's executor was previously built with only
        # llm/tools/event_bus/model (4 of ExecutorAgent's 22 params) — see
        # tasks/specs/side_constraint_integrity_plan.md Phase 0. This factory
        # wires the container-level singletons that request has no way to
        # supply on its own. Per-flow/per-session values (skill_prompt,
        # agent_role, harness block, behavioral_learner, middleware_chain,
        # trajectory_config) are NOT available here — the Mediator is a
        # shared singleton built once at container-construction time, before
        # any session exists — and remain a follow-up (Phase 7 wires
        # behavioral_learner specifically).
        def _executor_factory(*, model: str, session):
            from weebot.application.agents.executor import ExecutorAgent
            from weebot.application.models.tool_collection import ToolCollection
            from weebot.infrastructure.observability.tracing_adapter import TracingAdapter

            return ExecutorAgent(
                llm=llm,
                tools=tools if tools is not None else ToolCollection(),
                event_bus=event_bus,
                model=model,
                skill_retriever=self._maybe_get_str("skill_retriever"),
                personality=self._maybe_get_str("personality"),
                state_repo=state_repo,
                tracing_port=(
                    self._maybe_get(TracingAdapter) if self._is_tracing_enabled() else None
                ),
                # THE place the pool has to go. ExecutingState runs every step
                # through the mediator ("CQRS: execute step through mediator
                # (REQUIRED)"), and this factory builds the executor that
                # ExecuteStepHandler uses. PlanActFlow's own `self._executor`
                # only serves the summarize fallback. The remediation plan said
                # to pass the pool at `_base.py:283` via the flow's constructor
                # chain; doing that would have bounded an executor that never
                # runs a step, and the DI census would have gone green anyway,
                # because it proves a key is resolved -- not that it reaches the
                # object doing the work.
                llm_pool=self._maybe_get_str("llm_pool"),
                provider_account=self._maybe_get(ProviderAccountPort),
            )

        register_default_handlers(
            mediator,
            state_repo,
            task_runner,
            llm=llm,
            tools=tools,
            event_bus=event_bus,
            scoring_port=scoring_port,
            trajectory_builder=trajectory_builder,
            executor_factory=_executor_factory,
            trajectory_repo=trajectory_repo,
        )
        return mediator

    def build_chat_flow(self, session, model=None):
        """Construct a ChatFlow for conversational sessions."""
        from weebot.application.flows.chat_flow import ChatFlow
        from weebot.application.services.session_scoped_event_bus import SessionScopedEventBus

        return ChatFlow(
            llm=self.get(LLMPort),
            session=session,
            event_bus=SessionScopedEventBus(self.get(EventBusPort), session.id),
            model=model,
            mediator=self._maybe_get(Mediator),
            state_repo=self.get(StateRepositoryPort),
        )

    # ── internal helpers ───────────────────────────────────────────

    @staticmethod
    def _is_tracing_enabled() -> bool:
        from weebot.config.feature_flags import OTEL_TRACING_ENABLED

        return OTEL_TRACING_ENABLED

    @staticmethod
    def _is_kg_extraction_enabled() -> bool:
        from weebot.config.feature_flags import KNOWLEDGE_GRAPH_EXTRACTION_ENABLED

        return KNOWLEDGE_GRAPH_EXTRACTION_ENABLED

    def _maybe_get(self, port_type: type) -> Any | None:
        """Return registered instance or None if not bound."""
        try:
            return self.get(port_type)
        except KeyError:
            return None

    def _maybe_get_str(self, key: str) -> Any | None:
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

        retry = RetryWithBackoff(BackoffConfig(delays=[0.5, 1.0, 2.0], jitter=0.25))
        return SessionPersistenceAdapter(repo=self.get(StateRepositoryPort), retry=retry)

    def _create_swarm_bus(self):
        """Create a SwarmEventBus."""
        from weebot.infrastructure.swarm_event_bus import SwarmEventBus

        return SwarmEventBus()

    def _create_sub_agent_factory(self):
        """Create a SubAgentFactory."""
        from weebot.infrastructure.adapters.sub_agent_factory import SubAgentFactory
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.tools.tool_registry import RoleBasedToolRegistry

        sandbox = self._maybe_get(SandboxPort)
        registry = RoleBasedToolRegistry()

        def _flow_factory(s):
            return self._build_plan_act_flow_for_session(s)

        from weebot.application.ports.llm_port import LLMPort

        tools = registry.create_tool_collection(
            role="admin",
            sandbox_port=sandbox,
            llm_port=self._maybe_get(LLMPort),
            flow_factory=_flow_factory,
        )

        from weebot.config.model_refs import (
            MODEL_CASCADE_TIER2,
            MODEL_CASCADE_TIER4,
            MODEL_ROLE_CODER,
        )
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
                # Was self._maybe_get("state_repo_port"), a string nothing
                # registers -- StateRepositoryPort is bound by type -- so every
                # sub-agent flow got None and never saved its session, which the
                # mediator's handlers load by id to plan and execute it.
                state_repo=self._maybe_get(StateRepositoryPort),
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

    def _maybe_get_model(self) -> str | None:
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
