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

from weebot.application.cqrs.behaviors.save_policy import SavePolicyBehavior
from weebot.application.cqrs.handlers import register_default_handlers
from weebot.application.cqrs.behaviors.logging import LoggingBehavior
from weebot.application.cqrs.behaviors.telemetry import TelemetryBehavior
from weebot.application.cqrs.behaviors.validation_gate import ValidationGateBehavior
from weebot.application.cqrs.mediator import Mediator
from weebot.config.model_refs import MODEL_DI_DEFAULT
from weebot.config.model_registry import ModelProvider
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.event_store_port import EventStorePort
from weebot.application.ports.tool_repository_port import ToolRepositoryPort
from weebot.application.ports.tracing_port import TracingPort
from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.optimizer_port import OptimizerPort
from weebot.application.ports.audit_port import AuditPort
from weebot.application.ports.config_port import ConfigPort
from weebot.application.ports.memory_port import MemoryPort
from weebot.application.ports.sandbox_port import SandboxPort
from weebot.application.ports.scoring_port import ScoringPort
from weebot.application.ports.speech_port import SpeechPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.ports.steering_port import SteeringPort
from weebot.application.ports.task_router_port import TaskRouterPort
from weebot.application.services.task_runner import TaskRunner
from weebot.config.harness.schema import HarnessConfig
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

        # Tracing — OTEL or no-op fallback
        self.register(TracingPort, self._create_tracing)

        # EventPublisher bridge — routes EventBroker-style calls to AsyncEventBus
        self.register(EventPublisher, self._create_event_bridge)

        # LLM port
        self.register(LLMPort, lambda: self._create_llm(default_model))

        # Sandbox port — NativeWindowsSandbox on Windows, DockerLinuxSandbox on Linux
        self.register(SandboxPort, self._create_sandbox)

        # ActivityStream — replaces StateCoordinator-managed stream
        self.register(
            "activity_stream",
            lambda: self._create_activity_stream(),
        )

        # ResponseCache — replaces StateCoordinator-managed cache
        self.register(
            "response_cache",
            lambda: self._create_response_cache(),
        )

        # CQRS Mediator (with pipeline behaviours)
        self.register(Mediator, self._create_mediator)

        # Task Runner
        self.register(TaskRunner, self._create_task_runner)

        # Steering — mid-execution user feedback (Phase 5)
        self.register(SteeringPort, self._create_steering)

        # Harness config — model-agnostic runtime configuration
        self.register(HarnessConfig, self._create_harness_config)

        # Task router — query classification (Enhancement 6)
        self.register(TaskRouterPort, self._create_task_router)

        # Personality manager — WEEBOT_CORE.md identity injection
        self.register("personality", self._create_personality)

        # Structured logger — JSON-formatted operational logging
        self.register("structured_logger", lambda: self._create_structured_logger())

        # Audit port — output verification
        self.register(AuditPort, lambda: self._create_audit_service())

        # Memory port — cross-session persistent memory
        self.register(MemoryPort, lambda: self._create_memory_adapter())

        # Config port — unified configuration access
        self.register(ConfigPort, lambda: self._create_config_adapter())

        # Speech port — voice I/O (Whisper on Windows, configurable)
        self.register(SpeechPort, lambda: self._create_speech())

        # Event Store — append-only audit log
        self.register(EventStorePort, lambda: self._create_event_store())

        # Tool Repository — knowledge/requirements/video persistence
        self.register(ToolRepositoryPort, lambda: self._create_tool_repo())

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
        mediator.add_pipeline_behavior(LoggingBehavior())
        mediator.add_pipeline_behavior(TelemetryBehavior())
        mediator.add_pipeline_behavior(
            SavePolicyBehavior(state_repo=self._maybe_get(StateRepositoryPort))
        )
        # Register default handlers (with LLM and tools for agent execution)
        state_repo = self.get(StateRepositoryPort)
        task_runner = self._maybe_get(TaskRunner)
        llm = self._maybe_get(LLMPort)
        event_bus = self._maybe_get(EventBusPort)

        # Build a minimal tool collection for the execution handler
        tools = None
        if llm is not None:
            from weebot.application.models.tool_collection import ToolCollection
            from weebot.tools.bash_tool import BashTool
            from weebot.tools.file_editor import StrReplaceEditorTool as FileEditorTool
            from weebot.tools.python_tool import PythonExecuteTool as PythonTool
            try:
                tools = ToolCollection(
                    BashTool(), FileEditorTool(), PythonTool()
                )
            except Exception:
                tools = None

        # Optional: scoring deps for trajectory scoring (registered by
        # configure_skillopt()).  Passed through when available so that
        # ScoreTrajectoryCommand works from the main PlanActFlow's
        # CompletedState without needing a full SkillOpt setup.
        scoring_port = self._maybe_get_str("scoring_port")
        trajectory_builder = self._maybe_get_str("trajectory_builder")

        register_default_handlers(
            mediator, state_repo, task_runner,
            llm=llm, tools=tools, event_bus=event_bus,
            scoring_port=scoring_port,
            trajectory_builder=trajectory_builder,
        )
        return mediator

    # ── internal helpers ────────────────────────────────────────────

    @staticmethod
    def _create_state_repo(db_path: str) -> StateRepositoryPort:
        import os
        if os.environ.get("WEEBOT_DB_BACKEND", "").lower() == "postgresql":
            from weebot.infrastructure.persistence.postgresql.state_repo import (
                PostgreSQLStateRepository,
            )
            repo = PostgreSQLStateRepository()
            return repo
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

    def _create_event_bridge(self) -> EventPublisher:
        """Create EventBrokerAdapter bridging to the global AsyncEventBus."""
        from weebot.infrastructure.events.broker_adapter import EventBrokerAdapter
        return EventBrokerAdapter(event_bus=self.get(EventBusPort))

    @staticmethod
    def _create_activity_stream():
        """Create an ActivityStream (was managed by StateCoordinator)."""
        from weebot.core.activity_stream import ActivityStream
        return ActivityStream()

    @staticmethod
    def _create_tool_repo():
        """Create the default SQLite-backed ToolRepository."""
        from weebot.infrastructure.persistence.sqlite_tool_repo import (
            SQLiteToolRepository,
        )
        return SQLiteToolRepository()

    @staticmethod
    def _create_structured_logger():
        """Create the StructuredLogger singleton."""
        from weebot.core.structured_logger import StructuredLogger
        return StructuredLogger("weebot")

    @staticmethod
    def _create_config_adapter():
        """Create the default ConfigAdapter."""
        from weebot.infrastructure.adapters.config_adapter import ConfigAdapter
        return ConfigAdapter()

    @staticmethod
    def _create_audit_service():
        """Create the default AuditService."""
        from weebot.application.services.audit_service import AuditService
        return AuditService()

    @staticmethod
    def _create_memory_adapter():
        """Create the default FileSystemMemoryAdapter."""
        from weebot.infrastructure.persistence.filesystem_memory import (
            FileSystemMemoryAdapter,
        )
        return FileSystemMemoryAdapter()

    @staticmethod
    def _create_speech():
        """Create the default speech adapter."""
        from weebot.infrastructure.adapters.speech.whisper_adapter import (
            WhisperSpeechAdapter,
        )
        return WhisperSpeechAdapter()

    @staticmethod
    def _create_event_store():
        """Create the default SQLite-backed EventStore."""
        from weebot.infrastructure.event_store import EventStore
        return EventStore()

    @staticmethod
    def _create_response_cache():
        """Create a ResponseCache (was managed by StateCoordinator)."""
        from weebot.infrastructure.persistence.response_cache import ResponseCache
        return ResponseCache()

    @staticmethod
    def _create_sandbox() -> SandboxPort:
        """Create the default sandbox implementation for the current platform.

        Respects the ``sandbox_mode`` setting (env var ``SANDBOX_MODE``):
          - ``auto`` (default): NativeWindowsSandbox on Windows,
            DockerLinuxSandbox on other platforms.
          - ``native``: force NativeWindowsSandbox.
          - ``docker``: force DockerLinuxSandbox.
          - ``wsl2``: force WSL2Sandbox.

        Raises ``RuntimeError`` if the requested mode is not available.
        """
        from weebot.config.settings import WeebotSettings
        settings = WeebotSettings()

        if settings.sandbox_mode != "auto":
            from weebot.infrastructure.sandbox.factory import SandboxFactory, MODE_TO_TYPE
            from weebot.application.ports.sandbox_port import SandboxConfig

            sandbox_type = MODE_TO_TYPE.get(settings.sandbox_mode.lower())
            if sandbox_type is None:
                raise ValueError(
                    f"Unknown sandbox_mode '{settings.sandbox_mode}'. "
                    f"Set SANDBOX_MODE to: auto, native, docker, wsl2."
                )
            factory = SandboxFactory()
            return factory.create(sandbox_type)

        # Legacy auto-detection — direct instantiation (async check
        # is skipped here; runtime will fail fast if unavailable).
        import sys as _sys
        if _sys.platform == "win32":
            from weebot.infrastructure.sandbox.native_windows import (
                NativeWindowsSandbox,
            )
            return NativeWindowsSandbox()
        from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox
        return DockerLinuxSandbox()

    @staticmethod
    def _create_llm(default_model: Optional[str]) -> LLMPort:
        from weebot.infrastructure.adapters.llm.adapter_factory import create_adapter
        model = default_model or MODEL_DI_FALLBACK
        provider = ModelProvider.from_model_name(model).value
        return create_adapter(provider, model=model)

    def _create_mediator(self) -> Mediator:
        return self.build_mediator()

    def _create_task_runner(self) -> TaskRunner:
        return TaskRunner(
            state_repo=self.get(StateRepositoryPort),
            event_bus=self.get(EventBusPort),
        )

    @staticmethod
    def _create_steering():
        from weebot.infrastructure.adapters.steering_adapter import (
            InMemorySteeringAdapter,
        )
        return InMemorySteeringAdapter()

    @staticmethod
    def _create_task_router():
        from weebot.application.services.keyword_task_router import (
            KeywordTaskRouter,
        )
        return KeywordTaskRouter()

    @staticmethod
    def _create_personality():
        from weebot.core.personality_manager import PersonalityManager
        return PersonalityManager()

    @staticmethod
    def _create_harness_config():
        from pathlib import Path
        import os

        version = os.getenv("WEEBOT_HARNESS_VERSION", "v0.1.0")
        config_path = (
            Path(__file__).resolve().parent.parent
            / "config" / "harness" / f"{version}.yaml"
        )
        if config_path.exists():
            return HarnessConfig.load(str(config_path))
        return HarnessConfig.default()

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
        """Register multi-agent tools (BrowserInspector + Dispatch + WorkflowOrchestrator).

        Call after configure_defaults() or instead of it.  These tools are also
        included in the 'admin' role via the tool registry so they are available
        without calling this method explicitly when using RoleBasedToolRegistry.
        """
        self.configure_defaults(db_path=db_path, default_model=default_model)

        self.register("browser_inspector_tool", self._create_browser_inspector)
        self.register("dispatch_agents_tool", self._create_dispatch_agents)
        self.register("workflow_orchestrator_tool", self._create_workflow_orchestrator)

    def _create_browser_inspector(self):
        from weebot.tools.browser_inspector import BrowserInspectorTool
        return BrowserInspectorTool()

    def _create_dispatch_agents(self):
        from weebot.tools.dispatch_agents import DispatchAgentsTool
        state_repo = self._maybe_get(StateRepositoryPort)

        def _flow_factory(session):
            return self._build_plan_act_flow_for_session(session)

        return DispatchAgentsTool(flow_factory=_flow_factory, state_repo=state_repo)

    def _create_workflow_orchestrator(self):
        from weebot.tools.workflow_orchestrator import WorkflowOrchestratorTool
        state_repo = self._maybe_get(StateRepositoryPort)

        def _flow_factory(session):
            return self._build_plan_act_flow_for_session(session)

        return WorkflowOrchestratorTool(flow_factory=_flow_factory, state_repo=state_repo)

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
            logger=self._maybe_get_str("structured_logger"),
        )

    # ═══════════════════════════════════════════════════════════════════
    # AgentWasp Capability Integration bindings
    # ═══════════════════════════════════════════════════════════════════

    def configure_agentwasp_capabilities(
        self,
        *,
        db_path: str = "./weebot_sessions.db",
    ) -> None:
        """Register AgentWasp capability services.

        Call after configure_defaults(). Registers:
        - Knowledge Graph (Capability 2)
        - Background Jobs (Capability 8)
        - Opportunity Engine (Capability 7)

        Truth Binding (Cap 1), Capability Tiers (Cap 4), Plan Critic (Cap 3),
        Behavioral Learning (Cap 5), and Self-Improvement (Cap 6) are
        registered via their respective factories.
        """
        # Knowledge Graph adapter + service
        self.register(
            "kg_adapter",
            lambda: self._create_kg_adapter(db_path),
        )
        self.register(
            "knowledge_graph",
            lambda: self._create_kg_service(),
        )

        # Behavioral Learner
        self.register(
            "behavioral_learner",
            lambda: self._create_behavioral_learner(),
        )

        # Opportunity Engine
        self.register(
            "opportunity_engine",
            lambda: self._create_opportunity_engine(db_path),
        )

    @staticmethod
    def _create_kg_adapter(db_path: str):
        from weebot.infrastructure.persistence.sqlite_knowledge_graph import (
            SQLiteKnowledgeGraph,
        )
        return SQLiteKnowledgeGraph(db_path=db_path)

    def _create_kg_service(self):
        from weebot.application.services.knowledge_graph import KnowledgeGraphService
        from weebot.application.ports.knowledge_graph_port import KnowledgeGraphPort
        adapter = self.get("kg_adapter")
        return KnowledgeGraphService(adapter=adapter)

    def _create_behavioral_learner(self):
        from weebot.application.services.behavioral_learner import (
            BehavioralLearner,
        )
        llm = self._maybe_get(LLMPort)
        return BehavioralLearner(llm=llm)

    def _create_opportunity_engine(self, db_path: str):
        from weebot.application.services.opportunity_engine import (
            OpportunityEngine,
        )
        kg = self._maybe_get_str("knowledge_graph")
        fts5 = self._maybe_get_str("fts5_search")
        return OpportunityEngine(knowledge_graph=kg, fts5_search=fts5)

    async def register_agentwasp_jobs(self, scheduler_db: str = "./weebot_jobs.db") -> None:
        """Register AgentWasp background jobs with the scheduler.

        Must be called after configure_agentwasp_capabilities() and after
        the application event loop has started.

        Args:
            scheduler_db: Path for APScheduler's SQLite job store.
        """
        from weebot.scheduling.scheduler import SchedulingManager

        mgr = SchedulingManager(db_path=scheduler_db)

        # Register callables for each job type
        kg = self._maybe_get_str("knowledge_graph")
        if kg is not None:
            async def kg_consolidation():
                stats = await kg.get_stats()
                logger.info("KG consolidation: %s", stats)
            mgr.register_callable("kg_consolidation", kg_consolidation)

        opp = self._maybe_get_str("opportunity_engine")
        if opp is not None:
            async def opportunity_scan():
                proposals = await opp.scan()
                logger.info("Opportunity scan: %d proposals", len(proposals))
            mgr.register_callable("opportunity_scan", opportunity_scan)

        learner = self._maybe_get_str("behavioral_learner")
        if learner is not None:
            async def behavioral_consolidation():
                rules = await learner.get_active_rules()
                logger.info("Behavioral consolidation: %d active rules", len(rules))
            mgr.register_callable("behavioral_consolidation", behavioral_consolidation)

        # Integrity check and memory cleanup are generic
        async def integrity_check():
            import subprocess
            import shutil
            issues = []
            # Check git status
            try:
                result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.stdout.strip():
                    issues.append(f"Uncommitted changes: {result.stdout.count(chr(10))} files")
            except Exception as e:
                issues.append(f"Git check failed: {e}")
            # Check disk space
            total, used, free = shutil.disk_usage(Path.cwd())
            free_gb = free // (2**30)
            if free_gb < 1:
                issues.append(f"Low disk space: {free_gb} GB free")
            logger.info("Integrity check: %s", issues or "all clear")
        mgr.register_callable("integrity_check", integrity_check)

        async def memory_cleanup():
            logger.info("Memory cleanup: archival of sessions >90 days old not yet implemented")
        mgr.register_callable("memory_cleanup", memory_cleanup)

        # Load jobs from config
        await mgr.load_from_config()

        # Start scheduler
        await mgr.start()

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
            lambda: self._create_validation_gate(harness),
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
        """Construct a ready-to-use SkillOptFlow.

        Each call builds a FRESH Mediator instance so that the shared
        singleton is never mutated.  This prevents duplicate pipeline
        behaviours accumulating on repeated calls (multiple training runs).
        """
        from weebot.application.flows.skill_opt_flow import SkillOptFlow

        # Build a scoped mediator with the same default handlers +
        # the validation gate + skillopt handlers for this flow.
        mediator = self.build_mediator()
        gate = self._maybe_get_str("validation_gate")
        if gate is not None:
            mediator.add_pipeline_behavior(gate)

        # Register SkillOpt-specific command handlers
        from weebot.application.cqrs.handlers import register_skillopt_handlers
        from weebot.application.services.trajectory_builder import (
            TrajectoryBuilder,
        )

        scoring_port = self.get(OptimizerPort)
        llm = self._maybe_get(LLMPort)
        trajectory_builder = TrajectoryBuilder(llm=llm)
        skill_store = self.get("skill_store")
        trajectory_repo = self.get("trajectory_repo")
        validation_gate = self._maybe_get_str("validation_gate")
        validation_runner = (
            getattr(validation_gate, "_validation_runner", None)
            if validation_gate else None
        )
        flow_factory = self._create_target_flow_factory()

        # Also register scoring_port and trajectory_builder as string-keyed
        # singletons so build_mediator picks them up on subsequent calls.
        self.register_instance("scoring_port", scoring_port)
        self.register_instance("trajectory_builder", trajectory_builder)

        register_skillopt_handlers(
            mediator,
            scoring_port=scoring_port,
            state_repo=self.get(StateRepositoryPort),
            trajectory_builder=trajectory_builder,
            skill_store=skill_store,
            trajectory_repo=trajectory_repo,
            validation_runner=validation_runner,
            flow_factory=flow_factory,
        )

        return SkillOptFlow(
            skill_name=skill_name,
            target_flow_factory=self._create_target_flow_factory(),
            optimizer=self.get(OptimizerPort),
            skill_store=self.get("skill_store"),
            trajectory_repo=self.get("trajectory_repo"),
            event_bus=self.get(EventBusPort),
            mediator=mediator,
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
        provider = ModelProvider.from_model_name(model_id).value
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

    def _create_validation_gate(self, harness: str = "direct_chat"):
        from weebot.application.cqrs.behaviors.validation_gate import ValidationGateBehavior
        from weebot.application.services.validation_runner import ValidationRunner

        llm = self._maybe_get(LLMPort)
        runner = ValidationRunner(
            task_runner=self.get(TaskRunner),
            flow_factory=self._create_target_flow_factory(),
            scoring_fn=self._create_scorer(harness, llm=llm),
        )
        gate = ValidationGateBehavior(validation_runner=runner)
        return gate

    def _create_target_flow_factory(self):
        """Return a callable that creates PlanActFlow with a given session."""
        llm = self.get(LLMPort)
        # We need a session-scoped tool collection — build a simple one
        from weebot.application.models.tool_collection import ToolCollection
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
                state_repo=self._maybe_get(StateRepositoryPort),
            )
        return factory

    @staticmethod
    def _create_scorer(harness: str = "direct_chat", llm=None):
        """Create a real ScoringPort based on harness type.

        Supports:
          - 'exact_match'  → ExactMatchScorer (string comparison)
          - 'execution'    → ExecutionResultScorer (output artifact comparison)
          - 'verifier'     → VerifierScorer (LLM-based, requires llm=)
          - anything else  → fallback heuristic scorer

        Returns a Callable[[Session], Awaitable[float]] for ValidationRunner.
        """
        if harness == "exact_match":
            from weebot.infrastructure.scoring.exact_match_scorer import (
                ExactMatchScorer,
            )
            scorer = ExactMatchScorer()
        elif harness == "execution":
            from weebot.infrastructure.scoring.execution_scorer import (
                ExecutionResultScorer,
            )
            scorer = ExecutionResultScorer()
        elif harness == "verifier" and llm is not None:
            from weebot.infrastructure.scoring.verifier_scorer import (
                VerifierScorer,
            )
            scorer = VerifierScorer(llm=llm)
        else:
            scorer = None

        if scorer is not None:
            async def real_scorer(session) -> float:
                result = await scorer.score(session)
                return result.score
            return real_scorer

        # Fallback: simple heuristic scorer (original placeholder)
        async def fallback_scorer(session) -> float:
            for event in session.events:
                if event.type == "error":
                    return 0.0
            if session.status.name == "COMPLETED":
                return 1.0
            return 0.5
        return fallback_scorer


    # ── startup validation ──────────────────────────────────────────

    def validate(self) -> list[str]:
        """Resolve every registered binding to catch misconfiguration early.

        Returns a list of error messages (empty if everything is OK).
        """
        errors: list[str] = []
        for port_type in list(self._bindings.keys()):
            if isinstance(port_type, str):
                continue  # string keys are service aliases, not ports
            try:
                self.get(port_type)
            except Exception as exc:
                errors.append(f"{port_type.__name__}: {exc}")
        return errors


# ── module-level convenience ────────────────────────────────────────

# NOTE: No global _default_container singleton.
# Callers must create their own Container() instance and call
# configure_defaults().  See web/main.py for the pattern.
# The get_container() function was removed in Phase 2.3.
