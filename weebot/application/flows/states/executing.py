"""Executing state for Plan-Act flow."""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.domain.models.event import AgentEvent, ErrorEvent, WaitForUserEvent
from weebot.domain.models.plan import StepStatus
from weebot.domain.models.session import SessionStatus

logger = logging.getLogger(__name__)

class ExecutingState(FlowState):
    """Handles the execution of individual steps in the plan."""
    status = AgentStatus.EXECUTING

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.summarizing import SummarizingState
        from weebot.application.flows.states.updating import UpdatingState

        if context._plan is None:
            yield ErrorEvent(error="No plan available during execution")
            return

        step = context._plan.get_next_step()
        if step is None:
            logger.info("All steps complete, transitioning to SUMMARIZING")
            context.set_state(SummarizingState())
            return

        # Check if step was already completed (prevent re-execution)
        if step.status == StepStatus.COMPLETED:
            logger.warning("Step %s already completed, skipping", step.id)
            context.set_state(UpdatingState())
            return

        # ── Capability 5: Behavioral Learning — extract rules from corrections ──
        # Dedup: only process one user message per session per 30-second window
        _dedup_key = f"blearn:{context._session.id}"
        _dedup_window = 30.0
        if context._behavioral_learner is not None and prompt:
            import time as _time
            now = _time.time()
            last = getattr(context, "_last_blearn_ts", {}).get(context._session.id, 0)
            if now - last > _dedup_window:
                try:
                    await context._behavioral_learner.learn_from_correction(
                        prompt,
                        {
                            "session_id": context._session.id,
                            "step_description": step.description if step else "",
                            "tool_name": "",
                        },
                    )
                except Exception as ble:
                    logger.warning("Behavioral learner error: %s", ble)
                if not hasattr(context, "_last_blearn_ts"):
                    context._last_blearn_ts = {}
                context._last_blearn_ts[context._session.id] = now
        # ────────────────────────────────────────────────────────────────────────

        # ── Phase 5: Steering — poll for mid-execution user feedback ──
        effective_prompt = prompt
        if context._steering is not None:
            steering_msg = await context._steering.poll(context._session.id)
            if steering_msg:
                logger.info(
                    "Steering received for session %s: %s",
                    context._session.id, steering_msg[:80],
                )
                effective_prompt = (
                    f"{prompt}\n\n[STEERING — the user says: {steering_msg}. "
                    "Adjust your approach immediately.]"
                )

        # Check for step repetition limit (prevent infinite loops)
        step_exec_count = context._step_execution_counts.get(step.id, 0) + 1
        context._step_execution_counts[step.id] = step_exec_count

        if step_exec_count > context._max_step_repetitions:
            logger.warning(
                "Step %s executed %d times (limit: %d). Forcing completion.",
                step.id, step_exec_count, context._max_step_repetitions
            )
            yield ErrorEvent(
                error=f"Step '{step.description}' repeated {step_exec_count} times. "
                      f"Agent may be stuck in a loop. Completing task."
            )
            context.set_state(SummarizingState())
            return

        # Mark step as RUNNING before execution so the executor and
        # mediator see the correct state.
        context._plan = context._plan.update_step_status(step.id, StepStatus.RUNNING)
        logger.info("Executing step %s: %s", step.id, step.description)

        # Initialize flags before the event consumption paths
        hitl_paused = False
        execution_failed = False
        inner_facts = {}
        inner_should_terminate = False

        # --- CQRS: execute step through mediator ---
        if context._mediator:
            from weebot.application.cqrs.commands import ExecuteStepCommand
            cmd_result = await context._mediator.send(
                ExecuteStepCommand(
                    session_id=context._session.id,
                    step_id=step.id,
                    model=context._model or "",
                    tools=[t.name for t in context._tools],
                )
            )
            if not cmd_result.success:
                yield ErrorEvent(
                    error=f"Step execution rejected: {cmd_result.error}"
                )
                context.set_state(UpdatingState())
                return

            # Consume events from the mediator result.
            # inner_facts and inner_should_terminate are already
            # initialised above; the direct-call path fills them in.
            # Consume events via shared reconstructor.
            from weebot.application.cqrs.event_reconstructor import reconstruct_events
            for event in reconstruct_events(cmd_result.data.get("events", [])):
                await context._emit(event)
                yield event
                if isinstance(event, WaitForUserEvent):
                    hitl_paused = True
                elif isinstance(event, ErrorEvent):
                    execution_failed = True
                # Reconstruct shutdown signals from the serialised events
                if getattr(event, "type", "") == "tool" and getattr(event, "tool_name", "") == "terminate":
                    inner_should_terminate = True
        else:
            # Fallback: direct agent call.
            import warnings
            warnings.warn(
                "ExecutingState: no mediator, using direct executor call. "
                "Pipeline behaviors (logging, validation, telemetry) will NOT fire.",
                DeprecationWarning, stacklevel=2,
            )
            # Pass prompt (with any steering) as user_input so resume
            # answers and mid-execution feedback reach the LLM.
            async for event in context._executor.execute_step(
                context._plan, step, user_input=effective_prompt
            ):
                await context._emit(event)
                yield event
                if isinstance(event, WaitForUserEvent):
                    hitl_paused = True
                elif isinstance(event, ErrorEvent):
                    execution_failed = True
            # Use the flow's executor state only in direct-call path
            inner_facts = context._executor.facts
            inner_should_terminate = context._executor.should_terminate

        if hitl_paused:
            logger.info("Step %s paused for human input", step.id)
            context._session = context._session.set_status(SessionStatus.WAITING)
            return

        if execution_failed:
            logger.warning("Step %s failed during execution; transitioning to UPDATING", step.id)
            context.set_state(UpdatingState())
            return

        # Update step as completed
        context._plan = context._plan.update_step_status(step.id, StepStatus.COMPLETED)

        # Persist any facts extracted by the executor BEFORE checking termination
        for key, value in inner_facts.items():
            context._session = context._session.set_fact(key, value)

        # ── Capability 2: Knowledge Graph — upsert discovered facts ──
        if context._knowledge_graph is not None:
            try:
                await context._knowledge_graph.extract_from_step_result(
                    step_description=step.description,
                    result=step.result or "",
                    session_id=context._session.id,
                )
            except Exception as kg_exc:
                logger.warning("Knowledge graph extraction failed: %s", kg_exc)
        # ────────────────────────────────────────────────────────────

        # Check if terminate was called
        if inner_should_terminate:
            logger.info("Terminate detected, completing task")
            context.set_state(SummarizingState())
            return

        # Check if all steps are now complete
        if context._auto_terminate_on_plan_complete and context._plan.is_complete():
            logger.info("All plan steps completed. Auto-terminating.")
            context.set_state(SummarizingState())
            return

        # Compact memory after each step
        context._session = context._compactor.compact_session(context._session)

        # If there is still a pending step, continue executing without forced replanning.
        # Replanning is handled on failures/uncertainty elsewhere.
        next_step = context._plan.get_next_step()
        if next_step is None:
            context.set_state(SummarizingState())
            return

        context.set_state(ExecutingState())
