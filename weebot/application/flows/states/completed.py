"""Completed state for Plan-Act flow."""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.domain.models.event import AgentEvent, DoneEvent, PlanEvent
from weebot.domain.models.plan import PlanStatus
from weebot.domain.models.session import SessionStatus

logger = logging.getLogger(__name__)

class CompletedState(FlowState):
    """Final state marking the end of the Plan-Act flow."""
    status = AgentStatus.COMPLETED

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.plan_act_flow import AgentStatus

        if context._plan:
            context._plan = context._plan.model_copy(update={"status": PlanStatus.COMPLETED})
            plan_dump = context._plan.model_dump()
            # Emit and yield the SAME event object so event bus consumers
            # and flow callers see identical event IDs / timestamps.
            completed = PlanEvent(status=PlanStatus.COMPLETED, plan=plan_dump)
            await context._emit(completed)
            yield completed

        context._session = context._session.set_status(SessionStatus.COMPLETED)
        if context._state_repo:
            await context._state_repo.save_session(context._session)
        context._step_execution_counts.clear()  # Reset for next run
        yield DoneEvent()

        # --- CQRS: score the trajectory if mediator is available ---
        if context._mediator:
            from weebot.application.cqrs.commands.trajectory_commands import (
                ScoreTrajectoryCommand,
            )
            try:
                await context._mediator.send(
                    ScoreTrajectoryCommand(
                        session_id=context._session.id,
                        harness="direct_chat",
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Trajectory scoring failed for session %s: %s",
                    context._session.id,
                    exc,
                )

        # ── SessionStamp emission (Hallmark-inspired) ──────────────────
        try:
            from datetime import datetime, timezone
            from weebot.domain.models.stamp import SessionStamp, VerificationScores
            from weebot.application.services.plan_history import PlanHistory

            # Collect verification scores + gate failures from session context
            extra = getattr(context._session.context, "extra", {}) or {}
            scores_raw = extra.get("verification_scores", {})
            gate_failures = extra.get("gate_failures", [])

            verif_scores = VerificationScores(
                correctness=scores_raw.get("correctness", 3),
                completeness=scores_raw.get("completeness", 3),
                specificity=scores_raw.get("specificity", 3),
                restraint=scores_raw.get("restraint", 3),
            ) if scores_raw else None

            # Count tool calls and errors from session events
            from weebot.domain.models.event import ToolEvent, ErrorEvent
            tool_count = sum(1 for e in context._session.events if isinstance(e, ToolEvent))
            error_count = sum(1 for e in context._session.events if isinstance(e, ErrorEvent))

            # Build fingerprint from plan
            fingerprint = ""
            if context._plan:
                fingerprint = PlanHistory.plan_fingerprint(context._plan)

            stamp = SessionStamp(
                flow_type="PlanActFlow",
                model_used=getattr(context._executor, "_model", "") or "",
                plan_fingerprint=fingerprint,
                verification=verif_scores,
                gate_failures=gate_failures,
                tool_calls=tool_count,
                errors=error_count,
                duration_ms=0,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

            # Store stamp on session context
            context._session = context._session.model_copy(
                update={
                    "context": context._session.context.model_copy(
                        update={"stamp": stamp.model_dump()}
                    )
                }
            )
            logger.debug("SessionStamp emitted for %s: %s", context._session.id, stamp.plan_fingerprint)
        except Exception:
            logger.debug("SessionStamp emission failed — non-blocking", exc_info=True)

        logger.info("PlanActFlow completed for session %s", context._session.id)

        # Reset to IDLE for potential future runs in same session object
        # but the run loop in PlanActFlow will pick this up.
