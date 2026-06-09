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


async def _run_retention_review(
    agent, session_id, session_summary, trust_report, error_count, tool_count,
) -> None:
    """Run RetentionAgent as a background task — never blocks completion."""
    review = await agent.review(
        session_id, session_summary, trust_report, error_count, tool_count,
    )
    logger.info(
        "RetentionReview %s: %s — %s",
        session_id, review.verdict.value, review.reasoning[:120],
    )


async def _run_dream_scan() -> None:
    """Run DreamerAgent + IdeaGate as background task after completion."""
    try:
        from weebot.application.di import Container
        from weebot.application.ports.event_store_port import EventStorePort

        c = Container()
        c.configure_defaults()
        dreamer = c.get("dreamer_agent")
        event_store = c.get(EventStorePort)
        if dreamer is None or event_store is None:
            return

        failed_events = await event_store.query_recent_events(
            event_type="error", limit=30,
        )
        contracts = await dreamer.dream(
            opportunity_proposals=[],
            failed_step_events=failed_events,
            audit_violations=[],
            session_id="post_completion_scan",
        )
        if contracts:
            from weebot.application.services.intent_review_service import IntentReviewService
            from weebot.application.services.main_review_service import MainReviewService
            from weebot.application.services.idea_gate import IdeaGate
            from weebot.application.ports.llm_port import LLMPort

            llm = c.get(LLMPort)
            gate = IdeaGate(
                intent_reviewer=IntentReviewService(llm=llm),
                main_reviewer=MainReviewService(llm=llm),
            )
            approved = await gate.process(contracts)

            high_heat = [a for a in approved if a.heat_score >= 0.8]
            if high_heat:
                logger.info(
                    "Dream scan found %d approved ideas (%d high-heat) — run 'dream build <id>' to execute",
                    len(approved), len(high_heat),
                )
            else:
                logger.debug(
                    "Dream scan: %d contracts, %d approved, none auto-executable",
                    len(contracts), len(approved),
                )
    except Exception:
        logger.debug("Dream scan background task failed", exc_info=True)


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

        import time as _time
        _total_elapsed = _time.monotonic() - context._flow_started_at
        logger.info("PlanActFlow completed for session %s in %.1fs",
                    context._session.id, _total_elapsed)

        # ── Collect extra dict for TrustReport + RetentionReview ────
        _extra: dict = {}
        if hasattr(context._session.context, "extra"):
            _extra = context._session.context.extra.copy() or {}

        # ── TrustReport (Enhancement 4) ──────────────────────────────
        if getattr(context, "_trust_report_service", None) is not None:
            try:
                trust_report = await context._trust_report_service.compute(
                    session_id=context._session.id,
                    plan_steps=context._plan.steps if context._plan else [],
                    session_events=context._session.events,
                )
                _extra["trust_report"] = trust_report.model_dump()
                context._session = context._session.model_copy(
                    update={
                        "context": context._session.context.model_copy(
                            update={"extra": _extra}
                        )
                    }
                )
                logger.info(
                    "TrustReport session=%s band=%s confirmed=%d drift=%d regression=%d",
                    context._session.id, trust_report.trust_band.value,
                    trust_report.confirmed_count, trust_report.drift_count,
                    trust_report.regression_count,
                )
            except Exception:
                logger.debug("TrustReport failed — non-blocking", exc_info=True)

        # ── RetentionReview (Enhancement 5 — background, non-blocking) ──
        if getattr(context, "_retention_agent", None) is not None:
            _plan_for_retention = context._plan
            _trust_extra = _extra.get("trust_report", {})
            # Counts from events
            _tool_count_ret = sum(
                1 for e in context._session.events
                if getattr(e, "type", "") == "tool"
            )
            _error_count_ret = sum(
                1 for e in context._session.events
                if getattr(e, "type", "") == "error"
            )
            _session_summary = (
                f"{_plan_for_retention.title}: "
                + ", ".join(s.description for s in _plan_for_retention.steps[:5])
                if _plan_for_retention else "unknown"
            )
            import asyncio as _aio
            _aio.ensure_future(_run_retention_review(
                agent=context._retention_agent,
                session_id=context._session.id,
                session_summary=_session_summary,
                trust_report=_trust_extra,
                error_count=_error_count_ret,
                tool_count=_tool_count_ret,
            ))

        # ── Dream scan background (Enhancement 8) ─────────────────────
        import asyncio as _aio
        _aio.ensure_future(_run_dream_scan())

        # ── Hook: post_complete ────────────────────────────────────
        if getattr(context, "_hooks", None) is not None:
            from weebot.application.services.plan_history import PlanHistory
            _fp = PlanHistory.plan_fingerprint(context._plan) if context._plan else ""
            _tool_count = sum(
                1 for e in context._session.events
                if getattr(e, "type", "") == "tool"
            )
            _error_count = sum(
                1 for e in context._session.events
                if getattr(e, "type", "") == "error"
            )
            await context._hooks.execute_hooks("post_complete", {
                "session_id": context._session.id,
                "plan": context._plan,
                "tool_count": _tool_count,
                "error_count": _error_count,
                "total_elapsed_ms": _total_elapsed * 1000,
                "plan_fingerprint": _fp,
            })

        # Reset to IDLE for potential future runs in same session object
        # but the run loop in PlanActFlow will pick this up.
