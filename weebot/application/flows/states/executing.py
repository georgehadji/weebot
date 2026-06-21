"""Executing state for Plan-Act flow."""
from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.domain.models.event import AgentEvent, ErrorEvent, MessageEvent, ToolApprovalEvent, ToolEvent, WaitForUserEvent
from weebot.domain.models.plan import StepStatus
from weebot.domain.models.session import SessionStatus

logger = logging.getLogger(__name__)

# ── Code step detection helpers (Phase 8: per-step code review) ────
# Tool names whose presence indicates a code-producing step
_CODE_TOOL_NAMES: frozenset[str] = frozenset({
    "file_editor", "edit_file", "write_file", "create_file",
    "bash", "shell", "execute_command", "run_command",
    "write", "edit", "patch",
})

# Step description keywords that indicate code production
_CODE_KEYWORDS: frozenset[str] = frozenset({
    "implement", "write", "create file", "edit file", "modify",
    "add function", "add method", "add class", "fix bug",
    "refactor", "update file", "generate", "scaffold", "build",
    "code", "script", "patch",
})

# Reviewer retries gate — must match _MAX_REVIEW_RETRIES in ReviewingState
_MAX_REVIEW_RETRIES_GATE: int = 2


def _is_code_step(step: "Step", events: list[Any] | None = None) -> bool:
    """Return True if this step likely produced or modified code.

    Uses both keyword matching on the step description and, when available,
    tool-name inspection from captured execution events.
    """
    desc_lower = step.description.lower()
    if any(kw in desc_lower for kw in _CODE_KEYWORDS):
        return True
    if events:
        for e in events:
            if isinstance(e, dict):
                if e.get("tool_name", "") in _CODE_TOOL_NAMES:
                    return True
    return False


class ExecutingState(FlowState):
    """Handles the execution of individual steps in the plan."""
    status = AgentStatus.EXECUTING

    # ── Browser invocation audit ───────────────────────────────────

    @staticmethod
    def _audit_browser_invocation(context: "PlanActFlow") -> None:
        """Post-execution check: if plan mentions browser tools but none were invoked, warn.

        Scans plan step descriptions for browser-related keywords. If any match,
        checks session events for actual browser_navigator or advanced_browser calls.
        Emits WARNING if the plan expected browser interaction but none occurred.
        """
        _browser_kw = {
            "browser_navigator", "advanced_browser", "web_scraper", "browser_inspector",
            "navigate", "click", "fill", "screenshot", "compose", "login",
        }
        _plan = getattr(context, "_plan", None)
        if _plan is None or not hasattr(_plan, "steps"):
            return

        _plan_has_browser = any(
            any(kw in (s.description or "").lower() for kw in _browser_kw)
            for s in _plan.steps
        )
        if not _plan_has_browser:
            return

        # Check session events for browser tool calls
        _session = getattr(context, "_session", None)
        if _session is None:
            return

        _browser_called = any(
            getattr(e, "type", "") == "tool"
            and getattr(e, "tool_name", "") in ("browser_navigator", "advanced_browser")
            for e in _session.events
        )

        if not _browser_called:
            import logging as _log
            _log.getLogger("weebot.application.flows.states.executing").warning(
                "Plan contains browser-related steps (%d browser keywords found), "
                "but no browser tool was invoked during execution. "
                "The model may not support browser tool calls. "
                "Consider using a model with higher tool-use capability.",
                sum(1 for s in _plan.steps for kw in _browser_kw if kw in (s.description or "").lower()),
            )

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.verifying import VerifyingState
        from weebot.application.flows.states.updating import UpdatingState

        if context._plan is None:
            yield ErrorEvent(error="No plan available during execution")
            return

        step = context._plan.get_next_step()
        if step is None:
            logger.info("All steps complete, transitioning to VERIFYING")
            context.set_state(VerifyingState())
            return

        # Check if step was already completed (prevent re-execution)
        if step.status == StepStatus.COMPLETED:
            logger.warning("Step %s already completed, skipping", step.id)
            context.set_state(UpdatingState())
            return

        # ── Constraint enforcement (Enhancement 1 — S3 fix) ──────────────────
        # Check the next step against constraints extracted from the original task
        # before allowing execution. Uses ConstraintExtractor (regex-only, no LLM).
        # Skip when CONSTRAINT_CHECK_ENABLED=false (batch/automated runs).
        import os as _os_exec
        if _os_exec.environ.get("CONSTRAINT_CHECK_ENABLED", "").lower() == "false":
            _initial_prompt = ""
        else:
            _initial_prompt = (
                context._session.context.get("original_task", "")
                or context._session.context.get("last_prompt", "")
                or prompt
            )
        if _initial_prompt:
            from weebot.application.services.constraint_extractor import ConstraintExtractor
            _extractor = ConstraintExtractor()
            _constraints = _extractor.extract(_initial_prompt)
            _violations = _extractor.check_step(step.description, _constraints)
            if _violations:
                _violation_text = "; ".join(c.text for c in _violations[:2])
                logger.warning(
                    "Step '%s' may violate constraint: %s — pausing for user",
                    step.id, _violation_text,
                )
                _journal = getattr(context, "_misalignment_journal", None)
                if _journal is not None:
                    import asyncio as _asyncio
                    try:
                        from weebot.domain.models.misalignment_entry import MisalignmentEntry
                        _asyncio.ensure_future(_journal.record(MisalignmentEntry(
                            session_id=context._session.id,
                            project_path=context._session.context.get("working_dir", ""),
                            symptom="constraint_violation",
                            constraint_text=_violations[0].text,
                            step_description=step.description,
                        )))
                    except ImportError:
                        pass
                # Mark session as WAITING before yielding so resume works
                from weebot.domain.models.session import SessionStatus
                context._session = context._session.set_status(SessionStatus.WAITING)
                yield WaitForUserEvent(
                    question=(
                        f"Step '{step.description}' may violate a stated constraint:\n"
                        f"  {_violation_text}\n\n"
                        f"Type 'proceed' to allow this step, or describe an alternative approach."
                    )
                )
                return
        # ──────────────────────────────────────────────────────────────────────

        # ── Capability 5: Behavioral Learning — extract rules from corrections ──
        # Dedup: only process one user message per session per 30-second window
        _dedup_key = f"blearn:{context._session.id}"
        _dedup_window = 30.0
        if context._behavioral_learner is not None and prompt:
            import time as _time
            now = _time.monotonic()
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
            context.set_state(VerifyingState())
            return

        # Mark step as RUNNING before execution so the executor and
        # mediator see the correct state.
        context._plan = context._plan.update_step_status(step.id, StepStatus.RUNNING)
        logger.info("Executing step %s: %s", step.id, step.description)

        if getattr(context, "_hooks", None) is not None:
            _step_idx = next(
                (i for i, s in enumerate(context._plan.steps) if s.id == step.id), 0
            )
            await context._hooks.execute_hooks("pre_task", {
                "session_id": context._session.id,
                "step_id": step.id,
                "step_description": step.description,
                "step_index": _step_idx,
                "total_steps": len(context._plan.steps),
                "plan": context._plan,
            })

        # Initialize flags before the event consumption paths
        hitl_paused = False
        execution_failed = False
        inner_facts = {}
        inner_should_terminate = False

        # --- CQRS: execute step through mediator (REQUIRED) ---
        if context._mediator is None:
            yield ErrorEvent(
                error=(
                    "ExecutingState requires a Mediator to be configured on PlanActFlow. "
                    "Construct PlanActFlow with mediator=container.get(Mediator) or "
                    "use container.build_agent_runner()."
                )
            )
            context.set_state(UpdatingState())
            return

        import time as _time
        _step_t0 = _time.monotonic()
        from weebot.application.cqrs.commands import ExecuteStepCommand
        from weebot.config.model_refs import MODEL_BUDGET
        cmd_result = await context._mediator.send(
            ExecuteStepCommand(
                session_id=context._session.id,
                step_id=step.id,
                model=context._model or MODEL_BUDGET,
                tools=[t.name for t in context._tools],
            )
        )
        _step_elapsed = _time.monotonic() - _step_t0
        if not cmd_result.success:
            yield ErrorEvent(
                error=f"Step execution rejected: {cmd_result.error}"
            )
            context.set_state(UpdatingState())
            return

        # Consume events from the mediator result via shared reconstructor.
        from weebot.application.cqrs.event_reconstructor import reconstruct_events
        _current_step_events: list[Any] = []
        for event in reconstruct_events(cmd_result.data.get("events", [])):
            _current_step_events.append(event)
            await context._emit(event)
            yield event
            if isinstance(event, WaitForUserEvent):
                hitl_paused = True
            elif isinstance(event, ToolApprovalEvent):
                hitl_paused = True
                logger.info(
                    "Tool '%s' requires approval (risk=%s): %s",
                    event.tool_name, event.risk_level, event.reason,
                )
            elif isinstance(event, ErrorEvent):
                execution_failed = True
            # Reconstruct shutdown signals from the serialised events
            if getattr(event, "type", "") == "tool" and getattr(event, "tool_name", "") == "terminate":
                inner_should_terminate = True

        # ── Extract step result from execution events for quality validation ──
        _last_result_text = ""
        for event in _current_step_events:
            if isinstance(event, MessageEvent) and getattr(event, 'role', '') == 'assistant':
                msg = getattr(event, 'message', '') or ''
                if msg and len(msg) > len(_last_result_text):
                    _last_result_text = msg
            elif isinstance(event, ToolEvent):
                tr = getattr(event, 'result', '') or ''
                if tr and len(tr) > len(_last_result_text):
                    _last_result_text = tr
        if _last_result_text:
            step = step.model_copy(update={"result": _last_result_text})

        if hitl_paused:
            logger.info("Step %s paused for human input after %.1fs",
                        step.id, _step_elapsed)
            # Fire post_task on pause so observers track step timing
            if getattr(context, "_hooks", None) is not None:
                await context._hooks.execute_hooks("post_task", {
                    "session_id": context._session.id,
                    "step_id": step.id,
                    "step_description": step.description,
                    "elapsed_ms": _step_elapsed * 1000,
                    "plan": context._plan,
                })
            context._session = context._session.set_status(SessionStatus.WAITING)
            return

        if execution_failed:
            if getattr(context, "_hooks", None) is not None:
                await context._hooks.execute_hooks("on_error", {
                    "session_id": context._session.id,
                    "step_id": step.id,
                    "error": "step execution failed",
                    "error_type": "step_failure",
                    "plan": context._plan,
                })
            # If ALL models are circuit-broken, replanning will also fail.
            # Skip the replan cycle and go straight to terminal state.
            _all_tripped = any(
                "All models in the cascade have tripped" in getattr(e, "error", "")
                for e in cmd_result.data.get("events", [])
                if isinstance(e, dict) and e.get("type") == "error"
            )
            if _all_tripped:
                logger.warning(
                    "Step %s: all models tripped — skipping replan, forcing completion (%.1fs)",
                    step.id, _step_elapsed,
                )
                context._plan = context._plan.update_step_status(
                    step.id, StepStatus.COMPLETED
                )
                context.set_state(VerifyingState())
                return

            logger.warning("Step %s failed during execution in %.1fs; transitioning to UPDATING",
                           step.id, _step_elapsed)
            context.set_state(UpdatingState())
            return

        # ── Phase 3: Step-result quality check ──────────────────────
        # Gated on task_preset.enable_step_validation (default True).
        _sv_enabled = getattr(
            getattr(context, "_task_preset", None),
            "enable_step_validation", True,
        )
        if _sv_enabled and step.retry_count < 1:
            from weebot.application.services.step_result_validator import StepResultValidator
            _validator = StepResultValidator()
            validation = _validator.validate(
                result=str(step.result or ""),
                step_description=step.description,
                previous_result=None,
                step_events=_current_step_events,
            )
            if not validation.passed:
                logger.info(
                    "Step '%s' failed quality check (%s) — retrying with hint",
                    step.id, validation.reason,
                )
                # Inject quality hint into step description and retry
                updated_step = step.model_copy(update={
                    "description": f"{step.description}\n[Quality hint: {validation.quality_hint}]",
                    "retry_count": 1,
                    "status": StepStatus.PENDING,
                })
                context._plan = context._plan.replace_step(step.id, updated_step)
                # Stay in ExecutingState to retry the same step
                context.set_state(ExecutingState())
                return

        # ── Improvement 6: Step progress evaluation ────────────────
        _step_evaluator = getattr(context, "_step_evaluator", None)
        if _step_evaluator is not None and step.result:
            _prev_outputs = [
                s.result for s in context._plan.steps
                if s.is_done() and s.id != step.id and s.result
            ]
            _eval = await _step_evaluator.evaluate(
                step=step,
                output=str(step.result),
                plan=context._plan,
                previous_outputs=_prev_outputs,
            )
            if not _eval.passed:
                logger.warning(
                    "Step '%s' failed progress eval (score=%.2f, regression=%s): %s",
                    step.id, _eval.score, _eval.regression_detected, _eval.reasoning,
                )
                context.set_state(UpdatingState())
                return

        # Update step as completed, carrying the extracted result through
        context._plan = context._plan.update_step_status(
            step.id, StepStatus.COMPLETED, result=step.result or None,
        )
        logger.info("Step %s completed in %.1fs", step.id, _step_elapsed)

        if getattr(context, "_hooks", None) is not None:
            await context._hooks.execute_hooks("post_task", {
                "session_id": context._session.id,
                "step_id": step.id,
                "step_description": step.description,
                "elapsed_ms": _step_elapsed * 1000,
                "plan": context._plan,
            })

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
            context.set_state(VerifyingState())
            return

        # Check if all steps are now complete
        if context._auto_terminate_on_plan_complete and context._plan.is_complete():
            _audit_browser_invocation(context)
            logger.info("All plan steps completed. Auto-terminating.")
            context.set_state(VerifyingState())
            return

        # Compact memory after each step
        context._session = context._compactor.compact_session(context._session)

        # If there is still a pending step, continue executing without forced replanning.
        # Replanning is handled on failures/uncertainty elsewhere.
        next_step = context._plan.get_next_step()
        if next_step is None:
            context.set_state(VerifyingState())
            return

        # ── Phase 8: Per-step code review gate ──────────────────────
        # If a code reviewer is configured and this step produced code,
        # transition to ReviewingState instead of continuing directly.
        if (
            getattr(context, "_code_reviewer", None) is not None
            and _is_code_step(step, events=_current_step_events)
            and step.retry_count < _MAX_REVIEW_RETRIES_GATE
        ):
            from weebot.application.flows.states.reviewing import ReviewingState
            context.set_state(
                ReviewingState(
                    step=step,
                    reviewer=context._code_reviewer,
                    step_events=list(_current_step_events),
                )
            )
        else:
            context.set_state(ExecutingState())
