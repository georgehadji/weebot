"""Plan-Act flow — core state machine for autonomous task execution."""

from __future__ import annotations

import contextlib
import logging
from typing import Any, TYPE_CHECKING
from collections.abc import AsyncGenerator

from weebot.domain.services.session_lessons import project_key
from weebot.application.flows._plan_act_wiring import (
    compose_agents,
    config_from_legacy,
    wire_ports,
)
from weebot.application.flows.base_flow import BaseFlow
from weebot.application.flows._iteration_context import IterationContext
from weebot.application.flows.states.base import FlowState
from weebot.application.flows.states.planning import PlanningState
from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.base import AgentStatus
from weebot.application.flows.flow_router import FlowRouter
from weebot.application.flows.collaborators.session_budget import (
    enforce_budget,
    enforce_termination,
)
from weebot.application.flows.collaborators.tool_assembler import ToolAssembler

from weebot.core import cancel_requests


class PlanStuckError(RuntimeError):
    """Raised when the planner generates too many consecutive similar plans.

    This breaks the replanning loop and surfaces the stuck state to the
    operator rather than silently retrying with identical plans.
    """

    pass


from weebot.domain.services.continuation_detector import ContinuationDetector  # noqa: E402
from weebot.domain.models.event import AgentEvent, ErrorEvent  # noqa: E402
from weebot.domain.models.plan import Plan  # noqa: E402
from weebot.domain.models.session import SessionStatus  # noqa: E402
from weebot.application.models.plan_act_flow_config import PlanActFlowConfig  # noqa: E402

if TYPE_CHECKING:
    pass

# NOTE: Use self._logger (StructuredLogger) in instance methods.
# The module-level logger is a fallback for static/class methods only.
logger = logging.getLogger(__name__)

from weebot.application.services.metrics_bridge import (  # noqa: E402
    get_metrics as _get_metrics_bridge,
)


class PlanActFlow(BaseFlow):
    """Plan-Act agent flow with explicit state machine."""

    def __init__(self, config: PlanActFlowConfig | None = None, **legacy: Any):
        """Build the flow from a parameter object, or from the legacy loose keywords.

        The three jobs this used to do inline -- translating the loose keywords,
        assigning ~50 ports, composing the agents -- live in
        `_plan_act_wiring`; there is nothing left to do but call them in order.
        `**legacy` is the pre-parameter-object keyword surface, validated by name in
        `wire_ports`' module (see `LEGACY_KWARG_NAMES`); every name is a
        `PlanActFlowConfig` field with the same default, so both routes build the
        same flow.
        """
        cfg = (
            config
            if config is not None
            else config_from_legacy(**legacy)
        )
        wire_ports(self, cfg)
        compose_agents(self, cfg)


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
            len(self._plan_history.get_all()) if hasattr(self._plan_history, "get_all") else 0
        )
        plan_updates = max(plan_snapshots - 1, 0)  # first plan = 0 updates
        if plan_updates > 0:
            signals.append(f"replans={plan_updates}")

        # Signal 2: step repetition rate (>30% of steps retried)
        retried = sum(1 for count in self._step_execution_counts.values() if count > 1)
        retry_rate = retried / total_steps
        if retry_rate > 0.3:
            signals.append(f"retry_rate={retried}/{total_steps}")

        # Signal 3: plan critic was low confidence
        if self._plan_critique is not None:
            conf = getattr(self._plan_critique, "overall_confidence", None)
            if conf is not None and conf < 0.6:
                signals.append(f"critique_confidence={conf:.2f}")

        # Signal 4: heuristic splits applied during plan parsing
        heuristic_splits = getattr(self._plan, "heuristic_splits", 0)
        if heuristic_splits > 0:
            signals.append(f"heuristic_splits={heuristic_splits}")

        if not signals:
            return

        from weebot.domain.models.misalignment_entry import MisalignmentEntry

        entry = MisalignmentEntry(
            session_id=self._session.id,
            project_path=project_key(self._session.context.get("working_dir")),
            symptom="decomposition_quality",
            step_description=f"total_steps={total_steps}",
            constraint_text="; ".join(signals),
            correction_text="Proxy DA signals detected — review decomposition granularity",
        )
        await self._misalignment_journal.record(entry)
        self._log.info("Decomposition quality signals recorded: %s", "; ".join(signals))

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
        self._log.debug(
            "Skill gap recorded for step: %s", getattr(event, "step_description", "")[:80]
        )

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

    async def _pause_for_user(self, question: str) -> AgentEvent:
        """Pause for a human answer, durably. See `collaborators/user_pause.py`.

        Callers must mutate `self._session` with whatever has to survive
        before calling this, then `yield` the event it returns.
        """
        from weebot.application.flows.collaborators.user_pause import pause_flow_for_user

        return await pause_flow_for_user(self, question)

    async def _emit(self, event: AgentEvent) -> None:
        """Emit an event through EventPublisher.

        EventPublisher runs truth binding, credential sanitization, session
        mutation, event bus publishing and DB persistence, in that order.

        There used to be a second implementation of the same five steps -- the
        WP-4 EventPipeline -- taken instead whenever config.event_pipeline was
        set. Nothing ever set it: the container built the pipeline at startup,
        registered it, and discarded it. Deleted in phase 2.3. The only step it
        had that this path lacks was an audit-log write, which therefore never
        happened on any path.
        """
        publisher = self._get_event_publisher()
        # Sync publisher's session ref — the flow may have mutated
        # self._session (e.g. PlanReviewState setting WAITING status)
        # since the publisher was first constructed.
        publisher._session = self._session
        publisher._plan = self._plan  # truth binding and checkpoints read it
        self._session = await publisher.emit(event)

    async def _extract_session_constraints(self, prompt: str) -> None:
        """Extract, persist, and publish any side constraints in *prompt*.

        Delegates to SessionConstraintAccumulator (see collaborators/) —
        never raises, extraction is a Lost-in-Compaction mitigation, not a
        task requirement, and must not block the agentic loop (plan D9).
        """
        from weebot.application.flows.collaborators.session_constraint_accumulator import (
            SessionConstraintAccumulator,
        )

        if not hasattr(self, "_sc_accumulator"):
            self._sc_accumulator = SessionConstraintAccumulator(
                self._sc_extractor, state_repo=self._state_repo, event_bus=self._event_bus
            )
        if self._session_constraints is None:
            self._session_constraints = await self._sc_accumulator.hydrate(self._session.id)
        self._session_constraints = await self._sc_accumulator.extract_and_apply(
            self._session.id,
            prompt,
            self._session_constraints,
            turn_index=len(self._session.events),
        )

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
                with contextlib.suppress(Exception):
                    _m.flow_step_duration_seconds.labels(state=type(self._state).__name__).observe(
                        prev_duration
                    )

        # Each FlowState subclass declares its own status class attribute
        # so adding a new state does not require modifying this method.
        self._state = state
        self._state_entered_at = now
        self.status = getattr(state, "status", AgentStatus.IDLE)

        if prev_duration > 0.001:
            self._log.info(
                "Transition to state: %s (was in %s for %.1fs)",
                type(state).__name__,
                prev_name,
                prev_duration,
            )
        else:
            self._log.info("Transition to state: %s", type(state).__name__)
        # Trace the state transition (no-op if tracing port not wired)
        if self._tracing_port is not None:
            span = self._tracing_port.start_span(f"state.{type(state).__name__}")
            span.set_attribute("flow.session_id", self._session.id)
            span.set_attribute("state.name", type(state).__name__)
            span.end()

    async def run(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        """Run the flow with this session's ids bound to every log record (OBS-1)."""
        from weebot.core.log_context import log_context

        with log_context(session_id=self._session.id):
            if self._cost_meter is not None:
                # A resumed session starts from what it already spent.
                await self._cost_meter.seed(self._session.id)
            async for event in self._run_states(prompt):
                yield event

    async def _run_states(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        import time as _time

        self._flow_started_at = _time.monotonic()
        self._log.info(f"PlanActFlow started for session {self._session.id}")

        # ── OTEL tracing: plan_act_iteration span ────────────────────
        # ARCH-AUDIT-V2 B2 — root span for the full Plan-Act-Reflect loop.
        # Uses start_span (not start_as_current_span) because the generator
        # body makes context-manager teardown unreliable.  The span is
        # ended explicitly at the method's exit point below.
        # Gated on WEEBOT_OTEL_TRACING=true (default OFF).
        self._run_span = None
        if self._tracing_port is not None:
            from weebot.config.feature_flags import is_enabled

            if is_enabled("OTEL_TRACING_ENABLED"):
                self._run_span = self._tracing_port.start_span("plan_act_iteration")
                self._run_span.set_attribute("session.id", self._session.id)
                trace_id = getattr(self._session, "trace_id", None)
                if trace_id:
                    self._run_span.set_attribute("trace_id", trace_id)
        # Store the first substantive prompt so short follow-ups ("proceed", "yes")
        # can be enriched with it when a brand-new plan is needed.
        original_task: str = self._session.context.get("_original_task", "")
        if not original_task and prompt.strip():
            original_task = prompt.strip()
            self._session = self._session.model_copy(
                update={
                    "context": self._session.context.model_copy(
                        update={"original_task": original_task}
                    )
                }
            )

        # ── Lost-in-Compaction: extract session-scoped side constraints ──
        # Flow-entry seam — covers every real user turn (initial task,
        # resume, chat) since run() is invoked once per turn. Steering and
        # product-gate resume text are separate seams (Phase 3 follow-up).
        if self._sc_extractor is not None and prompt.strip():
            await self._extract_session_constraints(prompt)
        # ──────────────────────────────────────────────────────────────

        # Load durable behavioral rules once per flow. hydrate() is
        # idempotent and self-guarding; this is the only async seam that
        # runs before the executor builds its system prompt.
        if self._behavioral_learner is not None:
            try:
                await self._behavioral_learner.hydrate()
            except Exception as exc:
                logger.warning("Behavioral rule hydration failed: %s", exc)

        # Resolve effective prompt — enrich vague continuations via service
        effective_prompt = ContinuationDetector.resolve_prompt(
            user_prompt=prompt, original_task=original_task, event_count=len(self._session.events)
        )

        # ── Enhancement H1: scope external MCP tools to the current query ────
        if not hasattr(self, "_tool_assembler"):
            self._tool_assembler = ToolAssembler(
                registry=self._tool_registry,
                mcp_bridge=self._mcp_bridge,
                native_tool_selector=self._native_tool_selector,
                llm=self._llm,
                agent_role=self._agent_role or "admin",
                logger=self._stdlib_logger,
            )
        self._tools = await self._tool_assembler.assemble(
            effective_prompt=effective_prompt, tools=self._tools, executor=self._summary_executor
        )

        # ── Resolve initial state via FlowRouter ───────────────────────────
        initial_state, self._session = FlowRouter.resolve_initial_state(
            session=self._session,
            prompt=prompt,
            extra=self._session.context.extra if self._session.context else {},
        )
        if isinstance(initial_state, ExecutingState):
            # The step handler reloads the plan from the repo, so routing's
            # changes (an edited plan file, ICM B2) must be saved first.
            if self._state_repo is not None:
                await self._state_repo.save_session(self._session)
            last_plan = self._session.get_last_plan()
            self._plan = last_plan
            self.set_state(initial_state)
        elif isinstance(initial_state, PlanningState):
            # Record misalignment if user rejected the plan, then re-plan
            was_rejected = (
                self._session.context.extra.get("_plan_modification_request")
                if self._session.context and self._session.context.extra
                else None
            )
            if was_rejected and self._misalignment_journal is not None:
                await FlowRouter.record_misalignment(
                    session=self._session, prompt=was_rejected, journal=self._misalignment_journal
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
            await self._hooks.execute_hooks(
                "pre_execute",
                {"session_id": self._session.id, "prompt": effective_prompt, "plan": None},
            )

        max_iterations = self._max_iterations
        iteration_count = 0

        # Track whether this turn's user input has been "consumed" by a state.
        # It is handed to one state and to no other: `prompt` here means "what
        # the user said on this turn", so re-handing it to a later state would
        # replay the user's words as though they had just been said again.
        #
        # There used to be a reset here — `if type(self._state) !=
        # self._last_state_type: prompt_consumed = False` — meant to give each
        # new state type its own shot at the prompt. It never fired, because
        # `set_state` writes `_last_state_type` in the same call that writes
        # `_state`, so the comparison's two sides were always equal by the time
        # the loop looked. Both it and the field it read are gone. (D74.)
        #
        # It is deleted rather than repaired because making it fire is the
        # wrong repair. Two of the three uses of `prompt` in `ExecutingState`
        # want exactly this turn-input meaning and are correct today: the
        # executor appends it as a user turn "so the LLM sees the answer
        # instead of calling ask_human again", and the behavioural learner
        # passes it to `learn_from_correction`. Re-handing the original task on
        # every re-entry to ExecutingState would replay it to the model mid-plan
        # and mine it for behavioural rules as if it were a correction.
        #
        # The states that were starved by this are the ones that wanted the
        # *task*, not the turn input, and they now say so: see `task_text` in
        # states/base.py.
        prompt_consumed = False

        while iteration_count <= max_iterations:
            iteration_count += 1
            if cancel_requests.take(self._session.id):  # `flow cancel` from any process
                self._session = self._session.set_status(SessionStatus.FAILED)
                await self._emit(ErrorEvent(error="Cancelled on request (flow cancel)."))
                yield ErrorEvent(error="Cancelled on request (flow cancel).")
                break  # through the normal exit: hooks run, the run span ends

            current_state_type = type(self._state)

            # ── Build iteration context snapshot ──────────────────────
            ctx = IterationContext(
                session=self._session,
                plan=self._plan,
                current_state_name=(current_state_type.__name__ if self._state else "unknown"),
                similar_plan_count=getattr(self, "_similar_plan_count", 0),
                awm=self._awm,
            )

            # ── Composable termination check ──────────────────────────
            if self._termination_conditions:
                enforce_termination(self, iteration_count)

            # ── Session cost budget (plan 2.4, D6): ask at the hard limit ──
            if self._cost_meter is not None:
                paused = await enforce_budget(self)
                if paused:
                    for event in paused:
                        yield event
                    break  # paused and resumable; a grant lets the next run continue

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
                    model_id = self._model or self._summary_executor._model or ""
                    resolved_block = self._harness_resolver.resolve_instruction_block(model_id)
                    if resolved_block and resolved_block != self._harness_instruction_block:
                        self._harness_instruction_block = resolved_block
                        self._summary_executor.set_harness_block(resolved_block)
                except Exception as exc:
                    self._stdlib_logger.debug(
                        "Per-step harness resolution failed: %s — using previous block", exc
                    )

            # Execute current state.
            # Only pass the prompt if it's the first iteration or it's a re-planning loop
            # where the prompt is the original task.
            state_prompt = effective_prompt if not prompt_consumed else ""

            try:
                result = self._state.execute(self, state_prompt)
                # States may be async generators (yield events) or regular
                # coroutines (MetaAnalysisState does work then transitions).
                if hasattr(result, "__aiter__"):
                    async for event in result:
                        yield event
                        if state_prompt and event.type != "error":
                            prompt_consumed = True
                else:
                    await result  # coroutine — blocks until state transitions
            except PlanStuckError as stuck:
                self._log.error("Plan stuck: %s — terminating flow", stuck)
                if self._hooks is not None:
                    await self._hooks.execute_hooks(
                        "on_error",
                        {
                            "session_id": self._session.id,
                            "step_id": None,
                            "error": f"PLAN_STUCK: {stuck}",
                            "error_type": "plan_stuck",
                            "plan": self._plan,
                        },
                    )
                yield ErrorEvent(
                    error=(
                        f"Plan is stuck after {self._similar_plan_count} identical plans. "
                        f"The task may need a different approach. Error: {stuck}"
                    ),
                    error_code="PLAN_STUCK",
                )
                self._end_run_span()
                return  # terminate the flow gracefully
            finally:
                pass  # Inner generator cleaned up by Python GC on outer generator finalization

            # If we reached COMPLETED state logic or it paused for HITL, we break
            # FAILED too: CompletedState ends a run with failed steps that way.
            if self._session.status in (
                SessionStatus.COMPLETED, SessionStatus.WAITING, SessionStatus.FAILED
            ):
                break

            # If we are IDLE after state execution, we might be finished
            if self.status == AgentStatus.IDLE:
                break

        if self._hooks is not None:
            import time as _post_timer

            _post_elapsed = (_post_timer.monotonic() - self._flow_started_at) * 1000
            _total_tokens = 0
            await self._hooks.execute_hooks(
                "post_execute",
                {
                    "session_id": self._session.id,
                    "plan": self._plan,
                    "status": self._session.status.value,
                    "elapsed_ms": _post_elapsed,
                    "total_tokens": _total_tokens,
                },
            )

        # Enhancement 4: record decomposition quality proxy signals
        await self._record_decomposition_signals()

        if iteration_count > max_iterations:
            yield ErrorEvent(error=f"Max iterations ({max_iterations}) reached.")
        self._end_run_span()

    def _has_unresolved_wait_event(self) -> bool:
        """Check if the last WaitForUserEvent in the session has not been resolved."""
        return self._session.has_unresolved_wait_event()

    def _maybe_switch_model_for_context(self) -> str | None:
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
            facts=self._fact_resolver.resolve_for_session(self._session),
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
            self._plan, threshold=PLAN_SIMILARITY_THRESHOLD, window=PLAN_DIVERSIFICATION_WINDOW
        ):
            fp = self._plan_history.plan_fingerprint(self._plan)
            self._similar_plan_count = getattr(self, "_similar_plan_count", 0) + 1
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
                fp,
                self._similar_plan_count,
                self._MAX_SIMILAR_PLANS,
            )
        else:
            self._similar_plan_count = 0  # reset on a fresh plan

        self._plan_history.snapshot(self._plan)

    def undo(self) -> Plan | None:
        """Revert to the previous plan state if available."""
        self._plan = self._plan_history.undo(self._plan)
        return self._plan

    def redo(self) -> Plan | None:
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
        """Cumulative token usage: every step's executor plus the summary one."""
        total = dict(self._step_token_usage)
        own = getattr(self._summary_executor, "token_usage", None) or {}
        for key in total:
            total[key] += int(own.get(key, 0) or 0)
        return total

    def step_execution_context(self):
        """This flow's settings for the executor that runs the next step (ADR-015)."""
        from weebot.application.models.step_execution_context import StepExecutionContext

        return StepExecutionContext(
            tools=self._tools,
            harness_instruction_block=self._harness_instruction_block or None,
            pinned_model=self._model or None,
            **self._step_settings,
        )

    def record_step_usage(self, usage: dict | None, skill_gaps: list | None) -> None:
        """Add one step's token usage and skill gaps, as ExecuteStepHandler reports them."""
        for key in self._step_token_usage:
            self._step_token_usage[key] += int((usage or {}).get(key, 0) or 0)
        self.step_skill_gaps.extend(skill_gaps or [])

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

    def _end_run_span(self) -> None:
        """End the plan_act_iteration span once, on whichever exit the run takes."""
        if self._run_span is not None:
            self._run_span.end()
            self._run_span = None

    def _get_tracing_port(self):
        """Return the tracing port injected at construction time, or None."""
        return self._tracing_port
