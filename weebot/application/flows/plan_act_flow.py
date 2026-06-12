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

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.llm_port import LLMPort
from weebot.core.structured_logger import StructuredLogger
from weebot.application.services.memory_compactor import MemoryCompactor
from weebot.application.services.context_switcher import ContextSwitcher
from weebot.application.services.plan_history import PlanHistory


class PlanStuckError(RuntimeError):
    """Raised when the planner generates too many consecutive similar plans.

    This breaks the replanning loop and surfaces the stuck state to the
    operator rather than silently retrying with identical plans.
    """
    pass
from weebot.application.services.continuation_detector import (
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
        self._trust_report_service = cfg.trust_report_service  # TrustReportPort — enhancement 4
        self._retention_agent = cfg.retention_agent  # RetentionAgentPort — enhancement 5
        self._task_preset = cfg.task_preset  # Phase 5: cost/quality tier presets
        self._knowledge_graph = cfg.knowledge_graph
        self._behavioral_learner = cfg.behavioral_learner
        self._checkpoint_port = cfg.checkpoint_port
        self._hooks = cfg.hooks  # Optional[HookRegistry] — None = no-op
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
        self._episodic_memory = cfg.episodic_memory
        self._max_step_repetitions = cfg.max_step_repetitions
        self._auto_terminate_on_plan_complete = cfg.auto_terminate_on_plan_complete
        self._context_aware_model_selection = cfg.context_aware_model_selection
        self._max_iterations = cfg.max_iterations
        self._step_execution_counts: dict[str, int] = {}
        self._emit_lock = asyncio.Lock()

        self._skill_prompt = cfg.skill_prompt
        self._tracing_port = None
        self._persistence_adapter = None
        # ── Self-Harness: behavioural instruction block ──────────
        self._harness_instruction_block: str = ""
        if cfg.harness_config is not None:
            from weebot.application.services.harness_prompt_assembler import (
                HarnessPromptAssembler,
            )
            try:
                hc = cfg.harness_config
                self._harness_instruction_block = HarnessPromptAssembler.assemble(
                    instructions=hc.instructions,
                    runtime_control=hc.runtime_control,
                    subagents=hc.subagents,
                    skill_selection=hc.skill_selection,
                )
            except Exception as exc:
                self._stdlib_logger.warning(
                    "Failed to assemble harness instructions: %s — running without harness block",
                    exc,
                )
        # ──────────────────────────────────────────────────────────
        # ── Timing bookkeeping ────────────────────────────────────
        self._state_entered_at: float | None = None
        self._flow_started_at: float = 0.0
        # ──────────────────────────────────────────────────────────
        self._planner = PlannerAgent(
            llm=self._llm,
            event_bus=self._event_bus,
            model=self._model,
            skill_prompt=cfg.skill_prompt,
            facts=cfg.session.get_facts(),
            episodic_memory=cfg.episodic_memory,
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
        )
        if cfg.max_steps is not None:
            executor_kwargs["max_steps"] = cfg.max_steps
        self._executor = ExecutorAgent(**executor_kwargs)

    @property
    def _log(self):
        """Return the best available logger (StructuredLogger preferred)."""
        return self._logger if self._logger is not None else self._stdlib_logger

    async def _emit(self, event: AgentEvent) -> None:
        # ── Capability 1: Truth-binding response layer ──────────────
        # Before publishing, validate assistant responses against
        # deterministic guards (no LLM in the policy path).
        if (
            self._truth_binder is not None
            and isinstance(event, MessageEvent)
            and event.role == "assistant"
        ):
            result = await self._truth_binder.bind(
                event.message,
                {
                    "session_events": self._session.events,
                    "step": self._plan.current_step if self._plan else None,
                    "facts": self._session.get_facts(),
                },
            )
            if not result.passed or result.has_rewrites():
                self._log.info(
                    "Truth binding %s for response (%d violations)",
                    "blocked" if result.has_blockers() else "rewrote",
                    len(result.violations),
                )
                for v in result.violations:
                    self._log.debug("  Violation [%s]: %s", v.check, v.message)
                event = event.model_copy(update={"message": result.bound_text})
        # ────────────────────────────────────────────────────────────

        # ── Credential redaction for user-provided text ─────────────
        # Mask passwords, tokens, and API keys BEFORE they hit
        # session storage, the event bus, or the behavior ledger.
        if isinstance(event, MessageEvent) and event.role == "user":
            from weebot.core.credential_sanitizer import sanitize
            sanitized = sanitize(event.message or "")
            if sanitized != event.message:
                event = event.model_copy(update={"message": sanitized})
                self._log.info("Credential sanitizer redacted user input")
        # ────────────────────────────────────────────────────────────

        # 1. Mutate in-memory session (fast, no I/O, no lock needed)
        self._session = self._session.add_event(event)

        # 1a. Save checkpoint after step completions (best-effort, non-blocking)
        if event.type == "step":
            await self._maybe_save_checkpoint()

        # 2. Publish to event bus (async I/O, no lock needed)
        if self._event_bus:
            await self._event_bus.publish(event)
            # Publish domain events for key agent event types
            await self._emit_domain_event(event)

        # 3. Persist to DB — lock held only for serial write.
        #    Uses SessionPersistenceAdapter when available (retry + dead-letter);
        #    falls back to raw repo for backward compatibility.
        if self._state_repo:
            async with self._emit_lock:
                adapter = self._get_persistence_adapter()
                if adapter is not None:
                    ok = await adapter.save_session(self._session)
                    if not ok:
                        self._log.error(
                            "Session %s dead-lettered — persistence exhausted retries",
                            self._session.id,
                        )
                else:
                    try:
                        await self._state_repo.save_session(self._session)
                    except Exception as exc:
                        self._log.warning(
                            "Session persistence failed (retryable): %s", exc
                        )

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
            try:
                from weebot.infrastructure.observability import metrics as _m
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

        # Initial Resume/Start logic
        last_plan = self._session.get_last_plan()

        if last_plan is not None and not last_plan.is_complete():
            self._plan = last_plan
            self.set_state(ExecutingState())
            self._log.info("Resuming session %s with existing plan", self._session.id)
        elif self._session.status == SessionStatus.WAITING and last_plan is not None:
            self._plan = last_plan
            self.set_state(ExecutingState())
            self._log.info("Session %s was waiting, resuming execution", self._session.id)
        else:
            # Fresh session, or WAITING with no plan (from a failed prior run)
            self.set_state(PlanningState())

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
        prompt_consumed = False

        while iteration_count <= max_iterations:
            iteration_count += 1

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
