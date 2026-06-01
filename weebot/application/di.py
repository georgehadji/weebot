"""Dependency Injection container for weebot.

Centralizes port → adapter bindings so that the wiring lives in one
place rather than scattered across AgentRunner, factories, and web entry
points.

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

from weebot.application.cqrs.mediator import Mediator, ValidationGateBehavior
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.optimizer_port import OptimizerPort
from weebot.application.ports.scoring_port import ScoringPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.task_runner import TaskRunner
from weebot.domain.ports import EventPublisher


@dataclass
class Container:
    """Simple service-locator / DI container.

    Bindings are Callable factories (lazy) to avoid instantiating
    adapters that may never be used in a given process (e.g. browser
    in a CLI-only context).
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
            raise KeyError(f"No binding registered for {port_type.__name__}")

        instance = factory()
        self._singletons[port_type] = instance
        return instance

    # ── convenience binders ─────────────────────────────────────────

    def configure_defaults(
        self,
        *,
        db_path: str = "./weebot_sessions.db",
        default_model: Optional[str] = None,
    ) -> None:
        """Wire all defaults: LLM → OpenRouter, state → SQLite, etc."""
        # State repository
        self.register(StateRepositoryPort, lambda: self._create_state_repo(db_path))

        # Event bus
        self.register(EventBusPort, self._create_event_bus)

        # EventPublisher bridge — routes EventBroker-style calls to AsyncEventBus
        self.register(EventPublisher, self._create_event_bridge)

        # LLM port
        self.register(LLMPort, lambda: self._create_llm(default_model))

        # CQRS Mediator (with pipeline behaviours)
        self.register(Mediator, self._create_mediator)

        # Task Runner
        self.register(TaskRunner, self._create_task_runner)

    # ── high-level builders ─────────────────────────────────────────

    def build_agent_runner(
        self,
        role: str = "admin",
        mcp_config: Optional[dict] = None,
        use_rich: bool = True,
    ):
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
        mediator = Mediator()
        # Pipeline behaviours
        mediator.add_pipeline_behavior(
            __import__(
                "weebot.application.cqrs.mediator", fromlist=["LoggingBehavior"]
            ).LoggingBehavior()
        )
        # Register default handlers (with LLM and tools for agent execution)
        state_repo = self.get(StateRepositoryPort)
        task_runner = self._maybe_get(TaskRunner)
        llm = self._maybe_get(LLMPort)
        event_bus = self._maybe_get(EventBusPort)

        # Build a minimal tool collection for the execution handler
        tools = None
        if llm is not None:
            from weebot.tools.base import ToolCollection
            from weebot.tools.bash_tool import BashTool
            from weebot.tools.file_editor import FileEditorTool
            from weebot.tools.python_tool import PythonTool
            try:
                tools = ToolCollection(
                    BashTool(), FileEditorTool(), PythonTool()
                )
            except Exception:
                tools = None

        __import__(
            "weebot.application.cqrs.handlers", fromlist=["register_default_handlers"]
        ).register_default_handlers(
            mediator, state_repo, task_runner,
            llm=llm, tools=tools, event_bus=event_bus,
        )
        return mediator

    # ── internal helpers ────────────────────────────────────────────

    @staticmethod
    def _create_state_repo(db_path: str) -> StateRepositoryPort:
        from weebot.infrastructure.persistence.sqlite_state_repo import (
            SQLiteStateRepository,
        )
        return SQLiteStateRepository(db_path=db_path)

    @staticmethod
    def _create_event_bus() -> EventBusPort:
        from weebot.infrastructure.event_bus import AsyncEventBus
        return AsyncEventBus()

    def _create_event_bridge(self) -> EventPublisher:
        """Create EventBrokerAdapter bridging to the global AsyncEventBus."""
        from weebot.infrastructure.events.broker_adapter import EventBrokerAdapter
        return EventBrokerAdapter(event_bus=self.get(EventBusPort))

    @staticmethod
    def _create_llm(default_model: Optional[str]) -> LLMPort:
        from weebot.infrastructure.adapters.llm.adapter_factory import create_adapter
        model = default_model or "openrouter/auto"
        # Determine provider from model prefix
        if "/" in model:
            provider = "openrouter"
        elif model.startswith("claude"):
            provider = "anthropic"
        elif model.startswith("deepseek"):
            provider = "deepseek"
        else:
            provider = "openai"
        return create_adapter(provider, model=model)

    def _create_mediator(self) -> Mediator:
        return self.build_mediator()

    def _create_task_runner(self) -> TaskRunner:
        return TaskRunner(
            state_repo=self.get(StateRepositoryPort),
            event_bus=self.get(EventBusPort),
        )

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

    # ── Chatbot builder ─────────────────────────────────────────────

    def build_chat_flow(
        self,
        session: Session,
        model: Optional[str] = None,
    ):
        """Construct a ChatFlow for conversational sessions."""
        from weebot.application.flows.chat_flow import ChatFlow

        return ChatFlow(
            llm=self.get(LLMPort),
            session=session,
            event_bus=self.get(EventBusPort),
            model=model,
            mediator=self._maybe_get(Mediator),
            state_repo=self.get(StateRepositoryPort),
        )

    # ── internal helpers ───────────────────────────────────────────

    def _maybe_get_model(self) -> Optional[str]:
        """Return the default model string if LLM is bound."""
        return getattr(self, "_default_model", None)

    # ═══════════════════════════════════════════════════════════════════
    # Web-clone bindings
    # ═══════════════════════════════════════════════════════════════════

    def configure_web_clone(
        self,
        *,
        db_path: str = "./weebot_sessions.db",
        default_model: Optional[str] = None,
    ) -> None:
        """Register web-cloning tools (BrowserInspectorTool + DispatchAgentsTool).

        Call after configure_defaults() or instead of it.  Both tools are also
        included in the 'admin' role via the tool registry so they are available
        without calling this method explicitly when using RoleBasedToolRegistry.
        """
        self.configure_defaults(db_path=db_path, default_model=default_model)

        self.register("browser_inspector_tool", self._create_browser_inspector)
        self.register("dispatch_agents_tool", self._create_dispatch_agents)

    def _create_browser_inspector(self):
        from weebot.tools.browser_inspector import BrowserInspectorTool
        return BrowserInspectorTool()

    def _create_dispatch_agents(self):
        from weebot.tools.dispatch_agents import DispatchAgentsTool
        state_repo = self._maybe_get(StateRepositoryPort)

        def _flow_factory(session):
            return self._build_plan_act_flow_for_session(session)

        return DispatchAgentsTool(flow_factory=_flow_factory, state_repo=state_repo)

    def _build_plan_act_flow_for_session(self, session):
        """Build a PlanActFlow for a sub-agent session (used by DispatchAgentsTool)."""
        from weebot.application.flows.plan_act_flow import PlanActFlow
        from weebot.tools.tool_registry import RoleBasedToolRegistry
        from weebot.config.constants import SUBAGENT_MAX_STEPS

        registry = RoleBasedToolRegistry()
        tools = registry.create_tool_collection("admin", llm_port=self._maybe_get(LLMPort))
        return PlanActFlow(
            llm=self.get(LLMPort),
            tools=tools,
            state_repo=self._maybe_get(StateRepositoryPort),
            event_bus=self._maybe_get(EventBusPort),
            session=session,
            max_steps=SUBAGENT_MAX_STEPS,
        )

    # ═══════════════════════════════════════════════════════════════════
    # Skill Curator bindings
    # ═══════════════════════════════════════════════════════════════════

    def configure_skill_curator(self) -> None:
        """Register SkillCurator as a lazily-constructed singleton.

        Call after configure_defaults(). To activate the weekly cron job,
        also call await _register_curator_job() after the scheduler starts.
        """
        self.register("skill_curator", self._create_skill_curator)

    def _create_skill_curator(self):
        from weebot.application.skills.skill_registry import SkillRegistry
        from weebot.application.services.skill_curator import SkillCurator
        from weebot.application.ports.llm_port import LLMPort

        registry = SkillRegistry()
        llm = self._maybe_get(LLMPort)
        if llm is None:
            raise RuntimeError(
                "LLMPort must be configured before SkillCurator can be created. "
                "Call configure_defaults() before configure_skill_curator()."
            )
        return SkillCurator(registry=registry, llm=llm)

    async def register_curator_job(self, scheduler_db: str = "./weebot_jobs.db") -> None:
        """Register the SkillCurator as a weekly Sunday 02:00 cron job.

        Must be called after configure_skill_curator() and after the
        application event loop has started (i.e., inside an async context).

        Args:
            scheduler_db: Path for APScheduler's SQLite job store.
        """
        from weebot.scheduling.scheduler import SchedulingManager
        from weebot.application.services.skill_curator import SkillCurator

        curator = self.get("skill_curator")
        mgr = SchedulingManager(db_path=scheduler_db)
        mgr.register_callable("skill_curation", curator.run_curation)

        existing = await mgr.list_jobs()
        if not any(j.job_id == "weebot-skill-curator-weekly" for j in existing):
            await mgr.create_job(
                job_id="weebot-skill-curator-weekly",
                name="Weekly Skill Curation",
                trigger_type="cron",
                trigger_config={"day_of_week": "sun", "hour": 2, "minute": 0},
                callable_name="skill_curation",
                description="Classify and review stale skills weekly.",
            )
            logger.info("Registered weekly SkillCurator cron job")

        await mgr.start()

    # ═══════════════════════════════════════════════════════════════════
    # SkillOpt bindings
    # ═══════════════════════════════════════════════════════════════════

    def configure_skillopt(
        self,
        *,
        db_path: str = "./weebot_sessions.db",
        optimizer_model: str = "anthropic/claude-sonnet-4.6",
        target_model: Optional[str] = None,
        harness: str = "direct_chat",
    ) -> None:
        """Register SkillOpt-specific bindings on top of defaults.

        Args:
            db_path: Shared SQLite database path.
            optimizer_model: Stronger model ID for the optimizer.
            target_model: Model ID for the target (uses default if None).
            harness: Execution harness identifier.
        """
        self.configure_defaults(db_path=db_path, default_model=target_model)

        # Optimizer LLM — separate, stronger model
        self.register(
            "optimizer_llm",
            lambda: self._create_llm_by_id(optimizer_model),
        )

        # Optimizer agent (implements OptimizerPort)
        self.register(OptimizerPort, self._create_optimizer_agent)

        # Skill store
        self.register(
            "skill_store",
            lambda: self._create_skill_store(db_path),
        )

        # Trajectory repository
        self.register(
            "trajectory_repo",
            lambda: self._create_trajectory_repo(db_path),
        )

        # Validation gate behaviour on the mediator
        # (needs to be set up after mediator is created)
        self.register(
            "validation_gate",
            self._create_validation_gate,
        )

        # Evolution tracker (SIA-inspired longitudinal memory)
        self.register("evolution_tracker", self._create_evolution_tracker)

    def build_skill_opt_flow(
        self,
        skill_name: str,
        train_tasks: list[str],
        validation_tasks: Optional[list[str]] = None,
        output_path: str = "best_skill.md",
        epochs: int = 4,
        steps_per_epoch: int = 5,
        batch_size: int = 40,
        use_planning: bool = False,
    ):
        """Construct a ready-to-use SkillOptFlow."""
        from weebot.application.flows.skill_opt_flow import SkillOptFlow

        mediator = self.get(Mediator)
        # Wire the validation gate into the mediator's pipeline so that
        # ApplySkillEditsCommand actually runs held-out validation tasks.
        gate = self._maybe_get_str("validation_gate")
        if gate is not None:
            mediator.add_pipeline_behavior(gate)

        return SkillOptFlow(
            skill_name=skill_name,
            target_flow_factory=self._create_target_flow_factory(),
            optimizer=self.get(OptimizerPort),
            skill_store=self.get("skill_store"),
            trajectory_repo=self.get("trajectory_repo"),
            event_bus=self.get(EventBusPort),
            mediator=self.get(Mediator),
            epochs=epochs,
            steps_per_epoch=steps_per_epoch,
            batch_size=batch_size,
            minibatch_size=8,
            validation_tasks=validation_tasks or [],
            train_tasks=train_tasks,
            output_path=output_path,
            evolution_tracker=self._maybe_get_str("evolution_tracker"),
            use_planning=use_planning,
        )

    # ── SkillOpt internal helpers ───────────────────────────────────

    @staticmethod
    def _create_llm_by_id(model_id: str) -> LLMPort:
        from weebot.infrastructure.adapters.llm.adapter_factory import create_adapter
        if "/" in model_id:
            provider = "openrouter" if model_id.startswith("openrouter/") else "openrouter"
        elif model_id.startswith("claude"):
            provider = "anthropic"
        elif model_id.startswith("deepseek"):
            provider = "deepseek"
        else:
            provider = "openai"
        return create_adapter(provider, model=model_id)

    def _create_optimizer_agent(self) -> OptimizerPort:
        from weebot.application.agents.optimizer_agent import OptimizerAgent
        return OptimizerAgent(
            optimizer_llm=self.get("optimizer_llm"),
            event_bus=self.get(EventBusPort),
        )

    @staticmethod
    def _create_skill_store(db_path: str):
        from weebot.infrastructure.persistence.skill_store import SkillStore
        return SkillStore(db_path=db_path)

    @staticmethod
    def _create_trajectory_repo(db_path: str):
        from weebot.infrastructure.persistence.trajectory_repo import (
            TrajectoryRepository,
        )
        return TrajectoryRepository(db_path=db_path)

    def _create_evolution_tracker(self):
        from weebot.application.services.evolution_tracker import EvolutionTracker
        llm = self._maybe_get_str("optimizer_llm") or self._maybe_get(LLMPort)
        return EvolutionTracker(llm=llm)

    def _create_validation_gate(self):
        from weebot.application.cqrs.mediator import ValidationGateBehavior
        from weebot.application.services.validation_runner import ValidationRunner
        runner = ValidationRunner(
            task_runner=self.get(TaskRunner),
            flow_factory=self._create_target_flow_factory(),
            scoring_fn=self._create_default_scorer(),
        )
        gate = ValidationGateBehavior(validation_runner=runner)
        return gate

    def _create_target_flow_factory(self):
        """Return a callable that creates PlanActFlow with a given session."""
        llm = self.get(LLMPort)
        # We need a session-scoped tool collection — build a simple one
        from weebot.tools.base import ToolCollection
        from weebot.tools.bash_tool import BashTool
        tools = ToolCollection(BashTool())

        from weebot.application.flows.plan_act_flow import PlanActFlow

        def factory(session):
            return PlanActFlow(
                llm=llm,
                tools=tools,
                session=session,
                event_bus=self.get(EventBusPort),
                model=self._maybe_get_model(),
                mediator=self.get(Mediator),
            )
        return factory

    @staticmethod
    def _create_default_scorer():
        """Return a no-op scoring function (placeholder for real ScoringPort)."""
        async def noop_scorer(session) -> float:
            # Simple heuristic: check if session completed without error
            for event in session.events:
                if event.type == "error":
                    return 0.0
            if session.status.name == "COMPLETED":
                return 1.0
            return 0.5
        return noop_scorer


# ── module-level convenience ────────────────────────────────────────

_default_container: Optional[Container] = None


def get_container() -> Container:
    """Return the global container singleton, creating it lazily."""
    global _default_container
    if _default_container is None:
        _default_container = Container()
        _default_container.configure_defaults()
    return _default_container
