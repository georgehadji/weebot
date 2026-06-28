"""Plan-Act flow — core state machine for autonomous task execution."""
from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import AsyncGenerator, Optional, TYPE_CHECKING

from weebot.application.agents.executor import ExecutorAgent
from weebot.application.agents.planner import PlannerAgent
from weebot.application.flows.base_flow import BaseFlow
from weebot.application.flows.states.base import FlowState
from weebot.application.flows.states.planning import PlanningState
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.updating import UpdatingState
from weebot.application.flows.states.summarizing import SummarizingState
from weebot.application.flows.states.completed import CompletedState
from weebot.application.flows.states.base import AgentStatus
from weebot.application.flows.flow_router import FlowRouter

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.core.structured_logger import StructuredLogger
from weebot.application.termination.base import TerminationContext
from weebot.application.services.memory_compactor import MemoryCompactor
from weebot.application.services.context_switcher import ContextSwitcher
from weebot.application.services.plan_history import PlanHistory
from weebot.application.services.harness_prompt_assembler import HarnessPromptAssembler
from weebot.application.services.model_aware_harness_resolver import (
    ModelAwareHarnessResolver,
)


class PlanStuckError(RuntimeError):
    """Raised when the planner generates too many consecutive similar plans.

    This breaks the replanning loop and surfaces the stuck state to the
    operator rather than silently retrying with identical plans.
    """
    pass
from weebot.domain.services.continuation_detector import (
    ContinuationDetector,
)
from weebot.application.services.plan_critic import PlanCriticService
from weebot.application.services.truth_binder import TruthBinder
from weebot.domain.models.event import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    MessageEvent,
    PlanEvent,
    PlanStatus,
    StepEvent,
    StepStatus,
    WaitForUserEvent,
)
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session, SessionStatus
from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
from weebot.application.models.tool_collection import ToolCollection
from weebot.config.constants import DEFAULT_MAX_STEP_REPETITIONS, DEFAULT_MAX_FLOW_ITERATIONS

if TYPE_CHECKING:
    from weebot.application.cqrs.mediator import Mediator
    from weebot.application.ports.checkpoint_port import CheckpointPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort

# NOTE: Use self._logger (StructuredLogger) in instance methods.
# The module-level logger is a fallback for static/class methods only.
logger = logging.getLogger(__name__)

from weebot.application.services.metrics_bridge import get_metrics as _get_metrics_bridge


class PlanActFlow(BaseFlow):
    """Plan-Act agent flow with explicit state machine."""

    def __init__(
        self,
        config: PlanActFlowConfig = None,
        *,
        # ── Legacy kwargs — supported for backward compatibility ─────
        # All call sites should migrate to PlanActFlowConfig.
        llm: LLMPort = None,
        tools: ToolCollection = None,
        session: Session = None,
        event_bus: Optional[EventBusPort] = None,
        model: Optional[str] = None,
        skill_prompt: Optional[str] = None,
        episodic_memory = None,
        mediator: Optional[Mediator] = None,
        state_repo: Optional[StateRepositoryPort] = None,
        steering = None,
        max_step_repetitions: int = DEFAULT_MAX_STEP_REPETITIONS,
        max_iterations: int = DEFAULT_MAX_FLOW_ITERATIONS,
        auto_terminate_on_plan_complete: bool = True,
        context_aware_model_selection: bool = True,
        max_steps: Optional[int] = None,
        truth_binder: Optional[TruthBinder] = None,
        plan_critic: Optional[PlanCriticService] = None,
        code_reviewer: Optional[Any] = None,  # CodeReviewerPort
        knowledge_graph: Optional[Any] = None,
        behavioral_learner: Optional[Any] = None,
        logger: Optional["StructuredLogger"] = None,
        checkpoint_port: Optional["CheckpointPort"] = None,
        profile_name: Optional[str] = None,
        personality = None,
        agent_role: Optional[str] = None,
    ):
        # Normalize: if config is given use it; otherwise build from legacy kwargs.
        if config is not None:
            cfg = config
        else:
            cfg = PlanActFlowConfig(
                llm=llm,
                tools=tools,
                session=session,
                event_bus=event_bus,
                model=model,
                skill_prompt=skill_prompt,
                episodic_memory=episodic_memory,
                mediator=mediator,
                state_repo=state_repo,
                steering=steering,
                max_step_repetitions=max_step_repetitions,
                max_iterations=max_iterations,
                auto_terminate_on_plan_complete=auto_terminate_on_plan_complete,
                context_aware_model_selection=context_aware_model_selection,
                max_steps=max_steps,
                truth_binder=truth_binder,
                plan_critic=plan_critic,
                code_reviewer=code_reviewer,
                knowledge_graph=knowledge_graph,
                behavioral_learner=behavioral_learner,
                logger=logger,
                checkpoint_port=checkpoint_port,
                profile_name=profile_name,
                personality=personality,
                agent_role=agent_role,
            )

        self._llm = cfg.llm
        self._tools = cfg.tools
        self._session = cfg.session
        self._event_bus = cfg.event_bus
        self._model = cfg.model
        self._mediator = cfg.mediator
        self._state_repo = cfg.state_repo
        self._steering = cfg.steering
        self._truth_binder = cfg.truth_binder
        self._plan_critic = cfg.plan_critic
        self._plan_critique = None  # Set by CritiquingState
        self._code_reviewer = cfg.code_reviewer  # CodeReviewerPort — per-step code review
        self._step_evaluator = cfg.step_evaluator  # StepEvaluatorPort — per-step progress evaluation
        self._trust_report_service = cfg.trust_report_service  # TrustReportPort — enhancement 4
        self._retention_agent = cfg.retention_agent  # RetentionAgentPort — enhancement 5
        self._task_preset = cfg.task_preset  # Phase 5: cost/quality tier presets
        self._knowledge_graph = cfg.knowledge_graph
        self._behavioral_learner = cfg.behavioral_learner
        self._checkpoint_port = cfg.checkpoint_port
        self._hooks = cfg.hooks  # Optional[HookRegistry] — None = no-op
        self._misalignment_journal = cfg.misalignment_journal  # Optional[MisalignmentJournalPort]
        self._profile_name = cfg.profile_name
        self._agent_role = cfg.agent_role
        self._personality = cfg.personality
        self._logger = cfg.logger
        self._stdlib_logger = logging.getLogger(__name__)
        self.status = AgentStatus.IDLE
        self._state: FlowState = None  # Will be set in run()
        self._plan: Optional[Plan] = None
        self._compactor = MemoryCompactor()
        self._plan_history = PlanHistory()
        self._context_switcher = ContextSwitcher(llm=self._llm, event_bus=self._event_bus)
        self._awm = None  # AgentWorkflowMemory — lazy-init via _get_awm()
        self._episodic_memory = cfg.episodic_memory
        self._max_step_repetitions = cfg.max_step_repetitions
        self._planning_mode = getattr(cfg, "planning_mode", "auto")
        self._auto_terminate_on_plan_complete = cfg.auto_terminate_on_plan_complete
        self._context_aware_model_selection = cfg.context_aware_model_selection
        self._max_iterations = cfg.max_iterations
        self._termination_conditions = cfg.termination_conditions or []
        self._step_execution_counts: dict[str, int] = {}
        self._emit_lock = asyncio.Lock()
        self._event_publisher = None  # Lazy-init via _get_event_publisher()

        self._skill_prompt = cfg.skill_prompt
        self._skill_distiller = cfg.skill_distiller  # Phase 1 — None when flag is off
        self._tracing_port = None
        self._persistence_adapter = None
        # ── Event pipeline middleware (WP-4) ──────────────────────
        # Built in ``configure_defaults`` and injected via config.
        self._event_pipeline = getattr(cfg, "event_pipeline", None) or getattr(cfg, "_event_pipeline", None)

        # ── Self-Harness: behavioural instruction block + resolver ──
        self._harness_instruction_block: str = ""
        self._harness_config: Any = cfg.harness_config  # HarnessConfig
        self._harness_resolver: ModelAwareHarnessResolver | None = None

        if cfg.harness_config is not None:
            try:
                hc = cfg.harness_config
                self._harness_resolver = ModelAwareHarnessResolver(
                    base_config=hc,
                )
                self._harness_instruction_block = HarnessPromptAssembler.assemble(
                    instructions=hc.instructions,
                    runtime_control=hc.runtime_control,
                    subagents=hc.subagents,
                    skill_selection=hc.skill_selection,
                )
            except (AttributeError, TypeError, ValueError) as exc:
                self._stdlib_logger.error(
                    "Failed to assemble harness instructions: %s — running without harness block",
                    exc,
                    exc_info=True,
                )
        # ──────────────────────────────────────────────────────────
        # ── Timing bookkeeping ────────────────────────────────────
        self._state_entered_at: float | None = None
        self._flow_started_at: float = 0.0
        # ── Per-state prompt tracking: reset on state transition ─────
        self._last_state_type: type | None = None
        # ──────────────────────────────────────────────────────────
        self._planner = PlannerAgent(
            llm=self._llm,
            event_bus=self._event_bus,
            model=self._model,
            skill_prompt=cfg.skill_prompt,
            facts=cfg.session.get_facts(),
            episodic_memory=cfg.episodic_memory,
            skill_catalog=self._build_skill_catalog(cfg.skill_retriever),
        )
        executor_kwargs = dict(
            llm=self._llm,
            tools=self._tools,
            event_bus=self._event_bus,
            model=self._model,
            skill_prompt=cfg.skill_prompt,
            skill_retriever=cfg.skill_retriever,
            profile_name=cfg.profile_name,
            personality=cfg.personality,
            agent_role=cfg.agent_role,
            harness_instruction_block=self._harness_instruction_block
            if self._harness_instruction_block
            else None,
            middleware_chain=cfg.middleware_chain,
        )
        if cfg.max_steps is not None:
            executor_kwargs["max_steps"] = cfg.max_steps
        self._executor = ExecutorAgent(**executor_kwargs)

        # Enhancement 5: subscribe to SkillGapDetected domain events
        if self._event_bus is not None and self._misalignment_journal is not None:
            try:
                self._event_bus.subscribe_domain(self._on_skill_gap_detected)
            except Exception:
                pass  # subscription is best-effort

    # ── Skill catalog for planner ───────────────────────────────────

    @staticmethod
    def _build_skill_catalog(skill_retriever) -> str:
        """Build a compact skill summary for planner prompt injection.

        Walks the skill retriever's underlying registry to produce a Markdown
        list of available skills.  The planner uses this as step-boundary
        guidance — each step should align with exactly one skill's capability.

        Returns an empty string when no skills or no registry is available.
        """
        registry = None
        retriever = skill_retriever
        # Unwrap RerankingSkillRetriever decorator to reach the base retriever
        if hasattr(retriever, "_base"):
            retriever = retriever._base
        if hasattr(retriever, "_registry"):
            registry = retriever._registry

        if registry is None:
            return ""

        skills = registry.list_all()
        if not skills:
            return ""

        lines: list[str] = [
            "## Available Skills",
            "",
            "When decomposing the user's task into steps, align each step with",
            "exactly one skill capability from the list below.  Do NOT create steps",
            "for capabilities not listed — if a needed capability is missing,",
            "note it in the plan message and create a single informational step.",
            "",
        ]
        for name, skill in sorted(skills.items()):
            desc = getattr(skill, "description", "") or ""
            if len(desc) > 120:
                desc = desc[:117] + "..."
            lines.append(f"- **{name}**: {desc}")
        lines.append("")

        return "\n".join(lines)

    async def _record_decomposition_signals(self) -> None:
        """Record decomposition quality proxy signals in the misalignment journal.

        Called after execution completes.  Uses heuristic metrics as proxies
        for Decomposition Accuracy (DA) since weebot has no ground-truth
        labels.  Signals are purely diagnostic — no behavioural changes.
        """
        if self._misalignment_journal is None or self._plan is None:
            return

        signals: list[str] = []
        total_steps = max(len(self._plan.steps), 1)

        # Signal 1: plan was updated mid-execution (failure replan)
        # Each replan creates a snapshot in the plan history undo stack.
        plan_snapshots = (
            len(self._plan_history.get_all())
            if hasattr(self._plan_history, "get_all")
            else 0
        )
        plan_updates = max(plan_snapshots - 1, 0)  # first plan = 0 updates
        if plan_updates > 0:
            signals.append(f"replans={plan_updates}")

        # Signal 2: step repetition rate (>30% of steps retried)
        retried = sum(
            1 for count in self._step_execution_counts.values() if count > 1
        )
        retry_rate = retried / total_steps
        if retry_rate > 0.3:
            signals.append(f"retry_rate={retried}/{total_steps}")

        # Signal 3: plan critic was low confidence
        if self._plan_critique is not None:
            conf = getattr(self._plan_critique, "overall_confidence", None)
            if conf is not None and conf < 0.6:
                signals.append(f"critique_confidence={conf:.2f}")

        # Signal 4: heuristic splits applied during plan parsing
        heuristic_splits = getattr(self._plan, "_heuristic_splits", 0)
        if heuristic_splits > 0:
            signals.append(f"heuristic_splits={heuristic_splits}")

        if not signals:
            return

        from weebot.domain.models.misalignment_entry import MisalignmentEntry

        entry = MisalignmentEntry(
            session_id=self._session.id,
            project_path=(
                str(self._session.context.working_dir)
                if self._session.context
                else ""
            ),
            symptom="decomposition_quality",
            step_description=f"total_steps={total_steps}",
            constraint_text="; ".join(signals),
            correction_text="Proxy DA signals detected — review decomposition granularity",
        )
        await self._misalignment_journal.record(entry)
        self._log.info(
            "Decomposition quality signals recorded: %s",
            "; ".join(signals),
        )

    async def _on_skill_gap_detected(self, event) -> None:
        """Handle ``SkillGapDetected`` domain events (Enhancement 5).

        Records the gap in the misalignment journal for cross-session
        diagnostics.  The event bus delivers this; the callback must be
        registered as a subscriber during flow construction.

        Args:
            event: A ``SkillGapDetected`` domain event.
        """
        if self._misalignment_journal is None:
            return
        from weebot.domain.models.misalignment_entry import MisalignmentEntry

        entry = MisalignmentEntry(
            session_id=getattr(event, "session_id", ""),
            symptom="skill_gap",
            step_description=getattr(event, "step_description", ""),
            constraint_text=f"best_score={getattr(event, 'best_score', 0):.3f} < TAU_CREATE",
            correction_text="Consider authoring a new skill for this capability",
        )
        await self._misalignment_journal.record(entry)
        self._log.debug("Skill gap recorded for step: %s", getattr(event, "step_description", "")[:80])

    @property
    def _log(self):
        """Return the best available logger (StructuredLogger preferred)."""
        return self._logger if self._logger is not None else self._stdlib_logger

    def _get_event_publisher(self):
        """Return the shared EventPublisher instance (lazy-init)."""
        if self._event_publisher is None:
            from weebot.application.flows.event_publisher import EventPublisher
            self._event_publisher = EventPublisher(
                session=self._session,
                event_bus=self._event_bus,
                state_repo=self._state_repo,
                truth_binder=self._truth_binder,
                plan=self._plan,
                persistence_adapter=self._get_persistence_adapter(),
                hooks=self._hooks,
                emit_lock=self._emit_lock,
            )
        return self._event_publisher

    async def _emit(self, event: AgentEvent) -> None:
        """Emit an event through the middleware pipeline.

        Delegates to EventPublisher for the full pipeline:
        truth binding, credential sanitization, session mutation,
        event bus publishing, and DB persistence.
        If a pipeline has been configured (via ``_event_pipeline``), use it.
        """
        pipeline = getattr(self, "_event_pipeline", None)
        if pipeline is not None:
            context = {
                "session": self._session,
                "session_id": self._session.id if self._session else None,
                "flow": self,
                "event_bus": self._event_bus,
                "state_repo": self._state_repo,
                "emit_lock": self._emit_lock,
            }
            event = await pipeline.process(event, context)
            new_session = context.get("session")
            if new_session is not None:
                self._session = new_session
            return

        publisher = self._get_event_publisher()
        # Sync publisher's session ref — the flow may have mutated
        # self._session (e.g. PlanReviewState setting WAITING status)
        # since the publisher was first constructed.
        publisher._session = self._session
        self._session = await publisher.emit(event)

    async def _emit_domain_event(self, event: AgentEvent) -> None:
        """Publish domain events derived from agent events."""
        from weebot.domain.models.event import (
            PlanStepCompleted,
            FactDiscovered,
        )

        # Plan step completion
        if event.type == "step":
            step_id = getattr(event, "step_id", None) or getattr(event, "id", "unknown")
            domain_event = PlanStepCompleted(
                session_id=self._session.id,
                step_id=str(step_id),
            )
            await self._event_bus.publish_domain_event(domain_event)

        # Facts discovered (MessageEvent from assistant with new info)
        if event.type in ("message", "thought") and hasattr(event, "message"):
            msg = getattr(event, "message", "")
            if isinstance(msg, str) and len(msg) > 50:
                from hashlib import md5
                key = md5(msg.encode()).hexdigest()[:12]
                domain_event = FactDiscovered(
                    session_id=self._session.id,
                    key=key,
                    value=msg[:500],
                )
                await self._event_bus.publish_domain_event(domain_event)

    def is_done(self) -> bool:
        return self._session.status == SessionStatus.COMPLETED

    async def teardown(self) -> None:
        if self._tools is not None:
            await self._tools.teardown()

    def set_state(self, state: FlowState) -> None:
        """Change the current flow state.

        Records the transition time for the flow_step_duration_seconds
        Prometheus metric and logs per-state duration.
        """
        import time as _time
        now = _time.monotonic()
        prev_name = type(self._state).__name__ if self._state is not None else "start"
        prev_duration = (now - self._state_entered_at) if self._state_entered_at else 0.0

        # Record transition duration for the previous state
        if hasattr(self, "_state") and self._state is not None:
            _m = _get_metrics_bridge()
            if _m:
                try:
                    _m.flow_step_duration_seconds.labels(
                        state=type(self._state).__name__,
                    ).observe(prev_duration)
                except Exception:
                    pass  # metrics must never break state transitions

        # Each FlowState subclass declares its own status class attribute
        # so adding a new state does not require modifying this method.
        self._state = state
        self._state_entered_at = now
        self.status = getattr(state, "status", AgentStatus.IDLE)
        # Track state type for prompt_consumed reset in run()
        self._last_state_type = type(state)

        if prev_duration > 0.001:
            self._log.info("Transition to state: %s (was in %s for %.1fs)",
                            type(state).__name__, prev_name, prev_duration)
        else:
            self._log.info("Transition to state: %s", type(state).__name__)
        # Trace the state transition (no-op if tracing port not wired)
        if self._tracing_port is not None:
            span = self._tracing_port.start_span(f"state.{type(state).__name__}")
            span.set_attribute("flow.session_id", self._session.id)
            span.set_attribute("state.name", type(state).__name__)
            span.end()

    async def run(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        import time as _time
        self._flow_started_at = _time.monotonic()
        self._log.info(f"PlanActFlow started for session {self._session.id}")

        # --- Task context preservation ---
        # Store the first substantive prompt so short follow-ups ("proceed", "yes")
        # can be enriched with it when a brand-new plan is needed.
        original_task: str = self._session.context.get("_original_task", "")
        if not original_task and prompt.strip():
            original_task = prompt.strip()
            self._session = self._session.model_copy(
                update={"context": self._session.context.model_copy(
                    update={"original_task": original_task}
                )}
            )

        # Resolve effective prompt — enrich vague continuations via service
        effective_prompt = ContinuationDetector.resolve_prompt(
            user_prompt=prompt,
            original_task=original_task,
            event_count=len(self._session.events),
        )

        # ── Resolve initial state via FlowRouter ───────────────────────────
        initial_state, self._session = FlowRouter.resolve_initial_state(
            session=self._session,
            prompt=prompt,
            extra=self._session.context.extra if self._session.context else {},
        )
        if isinstance(initial_state, ExecutingState):
            last_plan = self._session.get_last_plan()
            self._plan = last_plan
            self.set_state(initial_state)
        elif isinstance(initial_state, PlanningState):
            # Record misalignment if user rejected the plan, then re-plan
            was_rejected = self._session.context.extra.get("_plan_modification_request") if self._session.context and self._session.context.extra else None
            if was_rejected and self._misalignment_journal is not None:
                await FlowRouter.record_misalignment(
                    session=self._session,
                    prompt=was_rejected,
                    journal=self._misalignment_journal,
                )
            self._plan = None

            # ── Product-mode gate: inject ProductGateState before planning ──
            from weebot.config.feature_flags import PRODUCT_MODE_ENABLED
            if PRODUCT_MODE_ENABLED:
                from weebot.application.flows.states.product_gate import ProductGateState
                self.set_state(ProductGateState())
            else:
                self.set_state(initial_state)
        else:
            self.set_state(initial_state)
        # ────────────────────────────────────────────────────────────────────

        if self._hooks is not None:
            await self._hooks.execute_hooks("pre_execute", {
                "session_id": self._session.id,
                "prompt": effective_prompt,
                "plan": None,
            })

        max_iterations = self._max_iterations
        iteration_count = 0

        # Track if the prompt has been "consumed" by a state that needs it.
        # This prevents an answer to step 1 from being injected as a prompt to step 2.
        # Reset on state transition so each new state gets one chance at the prompt.
        prompt_consumed = False

        while iteration_count <= max_iterations:
            iteration_count += 1

            # ── Reset prompt_consumed on state transition ────────────
            # Each FlowState gets one chance at the prompt.  When the state
            # type changes (e.g. ProductGateState → PlanningState), reset
            # so the new state can receive the task prompt even if the
            # previous state yielded events that consumed it.
            current_state_type = type(self._state)
            if current_state_type != self._last_state_type:
                prompt_consumed = False
                self._last_state_type = current_state_type

            # ── Composable termination check ──────────────────────────
            if self._termination_conditions:
                import time as _term_time
                _term_ctx = TerminationContext(
                    iteration=iteration_count,
                    total_tokens=self._executor.token_usage.get("total_tokens", 0),
                    elapsed_seconds=_term_time.monotonic() - self._flow_started_at,
                )
                for _tc in self._termination_conditions:
                    _result = _tc.check(_term_ctx)
                    if _result.should_terminate:
                        self._log.info("Termination condition met: %s", _result.reason)
                        from weebot.application.flows.states.completed import CompletedState
                        self.set_state(CompletedState(termination_reason=_result.reason))
                        return

            # ── Self-Harness: resolve harness instructions per-step ──
            # Before executing a state, check if we have a resolver and
            # the current state is one that uses the executor (ExecutingState).
            # Resolve instructions for the configured model and push them
            # to the executor so model-cascade switches get appropriate prompts.
            if self._harness_resolver is not None:
                try:
                    # NOTE: resolves against the *configured* model, not the
                    # cascade-chosen model.  Cascade selection happens inside
                    # ExecutorAgent._call_with_cascade() and does not propagate
                    # back.  Phase 7+ may add a post-step callback to track
                    # which model actually responded and re-resolve.
                    model_id = self._model or self._executor._model or ""
                    resolved_block = self._harness_resolver.resolve_instruction_block(
                        model_id,
                    )
                    if resolved_block and resolved_block != self._harness_instruction_block:
                        self._harness_instruction_block = resolved_block
                        self._executor.set_harness_block(resolved_block)
                except Exception as exc:
                    self._stdlib_logger.debug(
                        "Per-step harness resolution failed: %s — using previous block",
                        exc,
                    )

            # Execute current state.
            # Only pass the prompt if it's the first iteration or it's a re-planning loop
            # where the prompt is the original task.
            state_prompt = effective_prompt if not prompt_consumed else ""
            
            try:
                result = self._state.execute(self, state_prompt)
                # States may be async generators (yield events) or regular
                # coroutines (MetaAnalysisState does work then transitions).
                if hasattr(result, '__aiter__'):
                    async for event in result:
                        yield event
                        if state_prompt and event.type != "error":
                            prompt_consumed = True
                else:
                    await result  # coroutine — blocks until state transitions
            except PlanStuckError as stuck:
                self._log.error("Plan stuck: %s — terminating flow", stuck)
                if self._hooks is not None:
                    await self._hooks.execute_hooks("on_error", {
                        "session_id": self._session.id,
                        "step_id": None,
                        "error": f"PLAN_STUCK: {stuck}",
                        "error_type": "plan_stuck",
                        "plan": self._plan,
                    })
                yield ErrorEvent(
                    error=(
                        f"Plan is stuck after {self._similar_plan_count} identical plans. "
                        f"The task may need a different approach. Error: {stuck}"
                    ),
                    error_code="PLAN_STUCK",
                )
                return  # terminate the flow gracefully
            finally:
                pass  # Inner generator cleaned up by Python GC on outer generator finalization

            # ── Context compression at turn boundary (Track 3) ──────
            # If the session has accumulated many events, compress older
            # conversational turns to stay under the token budget.
            if len(self._session.events) > 20:
                try:
                    from weebot.application.services.context_manager import ContextManager
                    from weebot.application.services.lossy_context_compressor import (
                        LossyContextCompressor,
                    )

                    compressor = LossyContextCompressor()
                    mgr = ContextManager(engine=compressor)

                    # Convert events to message dicts for the compressor
                    msg_dicts = []
                    for ev in self._session.events:
                        if hasattr(ev, "role") and hasattr(ev, "message"):
                            msg_dicts.append({"role": ev.role, "content": ev.message or ""})

                    if msg_dicts:
                        result = await mgr.prepare(msg_dicts)
                        if result is not None:
                            summary = result.get("summary", "")
                            kept = result.get("retained_count", len(self._session.events))

                            # Build compressed session: keep system events,
                            # the most recent N message events, and inject the summary.
                            from weebot.domain.models.event import MessageEvent

                            # Keep non-message events (PlanEvent, StepEvent, etc.) +
                            # system messages + the compressed summary.
                            preserved: list = []
                            msg_events: list = []

                            for ev in self._session.events:
                                if hasattr(ev, "role") and hasattr(ev, "message"):
                                    msg_events.append(ev)
                                else:
                                    preserved.append(ev)

                            # Keep only the last few message events
                            keep_last = max(2, kept - 1)  # -1 for the summary
                            recent = msg_events[-keep_last:] if keep_last < len(msg_events) else msg_events

                            summary_event = MessageEvent(
                                role="system",
                                message=f"[Compressed context — earlier messages summarized]\n{summary[:500]}",
                            )

                            # Reconstruct: preserved non-message events → summary → recent messages
                            new_events = preserved + [summary_event] + recent
                            self._session = self._session.model_copy(update={"events": new_events})
                            self._log.info(
                                "Turn-boundary compression: %d→%d tokens, %d→%d events (iteration %d)",
                                result["original_token_count"],
                                result["compressed_token_count"],
                                len(self._session.events) if hasattr(self._session, "events") else 0,
                                len(new_events),
                                iteration_count,
                            )
                except Exception as exc:
                    self._stdlib_logger.debug("Turn-boundary compression skipped: %s", exc)
            # ─────────────────────────────────────────────────────────

            # If we reached COMPLETED state logic or it paused for HITL, we break
            if self._session.status in (SessionStatus.COMPLETED, SessionStatus.WAITING):
                break

            # If we are IDLE after state execution, we might be finished
            if self.status == AgentStatus.IDLE:
                break

        if self._hooks is not None:
            import time as _post_timer
            _post_elapsed = (_post_timer.monotonic() - self._flow_started_at) * 1000
            _total_tokens = 0
            await self._hooks.execute_hooks("post_execute", {
                "session_id": self._session.id,
                "plan": self._plan,
                "status": self._session.status.value,
                "elapsed_ms": _post_elapsed,
                "total_tokens": _total_tokens,
            })

        # Enhancement 4: record decomposition quality proxy signals
        await self._record_decomposition_signals()

        if iteration_count > max_iterations:
            yield ErrorEvent(error=f"Max iterations ({max_iterations}) reached.")

    def _has_unresolved_wait_event(self) -> bool:
        """Check if the last WaitForUserEvent in the session has not been resolved."""
        return self._session.has_unresolved_wait_event()

    def _maybe_switch_model_for_context(self) -> Optional[str]:
        """Dynamically select model based on context size if enabled.

        Delegates to ContextSwitcher service.

        Returns:
            New model ID if switch recommended, None otherwise.
        """
        # Allow disabling context-aware model selection via env var (batch mode)
        import os as _os_cam
        if _os_cam.environ.get("CONTEXT_AWARE_MODEL_SELECTION", "").lower() == "false":
            return None
        return self._context_switcher.maybe_switch_model_for_context(
            session=self._session,
            current_model=self._model,
            context_aware_enabled=self._context_aware_model_selection,
        )

    def _update_agents_with_model(self, model: str) -> None:
        """Update planner with a new model via ContextSwitcher.

        Args:
            model: The new model ID to use.
        """
        self._model = model
        self._planner = self._context_switcher.update_agents_with_model(
            model=model,
            skill_prompt=self._skill_prompt,
            facts=self._session.get_facts(),
            episodic_memory=self._episodic_memory,
        )

    # Maximum consecutive similar plans before raising PlanStuckError.
    _MAX_SIMILAR_PLANS: int = 3

    def _snapshot_plan(self) -> None:
        """Push current plan onto the PlanHistory undo stack.

        Also checks for structural similarity to recent plans (Hallmark-inspired
        diversification).  If the new plan is too similar, logs a warning.  After
        _MAX_SIMILAR_PLANS consecutive similar plans, raises PlanStuckError to
        break the replanning loop.
        """
        from weebot.config.constants import PLAN_DIVERSIFICATION_WINDOW, PLAN_SIMILARITY_THRESHOLD

        if self._plan is not None and self._plan_history.is_too_similar(
            self._plan,
            threshold=PLAN_SIMILARITY_THRESHOLD,
            window=PLAN_DIVERSIFICATION_WINDOW,
        ):
            fp = self._plan_history.plan_fingerprint(self._plan)
            self._similar_plan_count = getattr(self, '_similar_plan_count', 0) + 1
            if self._similar_plan_count >= self._MAX_SIMILAR_PLANS:
                raise PlanStuckError(
                    f"Plan is stuck: {self._similar_plan_count} consecutive plans "
                    f"with fingerprint similarity > {PLAN_SIMILARITY_THRESHOLD}. "
                    f"Last fingerprint: {fp}. The task may need a different approach "
                    f"or human intervention."
                )
            self._log.warning(
                "Plan fingerprint %s is too similar to recent plans "
                "(attempt %d/%d) — consider diversifying.",
                fp, self._similar_plan_count, self._MAX_SIMILAR_PLANS,
            )
        else:
            self._similar_plan_count = 0  # reset on a fresh plan

        self._plan_history.snapshot(self._plan)

    def undo(self) -> Optional[Plan]:
        """Revert to the previous plan state if available."""
        self._plan = self._plan_history.undo(self._plan)
        return self._plan

    def redo(self) -> Optional[Plan]:
        """Re-apply a plan state that was previously undone."""
        self._plan = self._plan_history.redo(self._plan)
        return self._plan

    @property
    def can_undo(self) -> bool:
        return self._plan_history.can_undo

    @property
    def can_redo(self) -> bool:
        return self._plan_history.can_redo

    @property
    def token_usage(self) -> dict[str, int]:
        """Cumulative token usage for this flow's executor."""
        if self._executor and hasattr(self._executor, "token_usage"):
            return self._executor.token_usage
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _get_persistence_adapter(self):
        """Return the session persistence adapter injected at construction time.

        Returns None when no adapter was provided (backward-compat: caller already
        guards with ``if adapter is not None``).
        """
        return self._persistence_adapter

    def _get_awm(self):
        """Return the shared AgentWorkflowMemory instance (lazy-init).

        The AWM is shared across all flow states so that workflow templates
        induced during session completion are visible to subsequent planning
        queries.
        """
        if self._awm is None and self._llm is not None:
            from weebot.application.services.workflow_memory import AgentWorkflowMemory
            self._awm = AgentWorkflowMemory(llm=self._llm)
        return self._awm

    async def _maybe_save_checkpoint(self) -> None:
        """Save a flow checkpoint if a CheckpointPort is wired.

        Called after each step event so that a crashed flow can resume
        from the last completed step.
        """
        if self._checkpoint_port is None or self._plan is None:
            return

        try:
            from weebot.domain.models.checkpoint import FlowCheckpoint, StepCheckpoint

            # Build completed step snapshots from the plan
            completed: list[StepCheckpoint] = []
            for step in self._plan.steps:
                if step.status.value in ("completed", "failed"):
                    completed.append(
                        StepCheckpoint(
                            step_id=step.id,
                            description=step.description,
                            status=step.status.value,
                            result=step.result,
                        )
                    )

            checkpoint = FlowCheckpoint(
                session_id=self._session.id,
                flow_type="PlanActFlow",
                current_state=type(self._state).__name__ if self._state else "planning",
                plan_snapshot=self._plan,
                completed_steps=completed,
                conversation_summary="",
                iteration_count=0,
            )
            await self._checkpoint_port.save(checkpoint)
            self._log.debug("Checkpoint saved for session %s", self._session.id)
        except Exception:
            self._log.warning(
                "Failed to save checkpoint for session %s",
                self._session.id,
                exc_info=True,
            )

    def _get_tracing_port(self):
        """Return the tracing port injected at construction time, or None."""
        return self._tracing_port
