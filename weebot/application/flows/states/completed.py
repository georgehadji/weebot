"""Completed state for Plan-Act flow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from collections.abc import AsyncGenerator

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState, task_text
from weebot.domain.models.event import AgentEvent, DoneEvent, PlanEvent
from weebot.domain.models.plan import PlanStatus, StepStatus
from weebot.domain.models.session import SessionStatus
from weebot.domain.models.event import ProductDecisionEvent
from datetime import UTC

logger = logging.getLogger(__name__)


def _background():
    """The owner for this state's post-completion work.

    Imported lazily so `completed.py` keeps its current import cost and the
    services package is not pulled in by anything that merely imports the flow
    states.
    """
    from weebot.application.services.background_tasks import get_background_tasks

    return get_background_tasks()


async def _run_retention_review(
    agent, session_id, session_summary, trust_report, error_count, tool_count
) -> None:
    """Run RetentionAgent as a background task — never blocks completion."""
    review = await agent.review(session_id, session_summary, trust_report, error_count, tool_count)
    logger.info(
        "RetentionReview %s: %s — %s", session_id, review.verdict.value, review.reasoning[:120]
    )


async def _run_skill_gap_processing(gaps: list[dict], session_id: str) -> None:
    """Submit skill-gap signals as IdeaContracts through the IdeaGate (Phase 2).

    Background task — never blocks CompletedState.  Runs after the flow
    yields DoneEvent so the user sees an immediate response.
    """
    from weebot.config.feature_flags import SKILL_GAP_TRIGGER_ENABLED

    if not SKILL_GAP_TRIGGER_ENABLED or not gaps:
        return
    try:
        from weebot.application.di import Container
        from weebot.application.ports.llm_port import LLMPort
        from weebot.application.services.idea_gate import IdeaGate
        from weebot.application.services.intent_review_service import IntentReviewService
        from weebot.application.services.main_review_service import MainReviewService
        from weebot.domain.models.idea_contract import IdeaContract, IdeaSource

        c = Container()
        c.configure_defaults()
        llm = c.get(LLMPort)

        contracts = [
            IdeaContract(
                title=f"Skill gap: {g['step'][:60]}",
                prompt=(
                    f"Create a reusable skill for tasks of type: {g['step']}\n"
                    f"(No useful skill was found; best retrieval score: {g['score']:.3f})"
                ),
                source=IdeaSource.OPPORTUNITY_PROPOSAL,
                source_ref=session_id,
                evidence=[f"retrieval_miss score={g['score']:.3f}"],
                heat_score=max(0.0, min(1.0, 1.0 - g["score"])),
                estimated_effort="low",
                dreamer_session_id=session_id,
            )
            for g in gaps
        ]

        gate = IdeaGate(
            intent_reviewer=IntentReviewService(llm=llm), main_reviewer=MainReviewService(llm=llm)
        )
        approved = await gate.process(contracts)
        if approved:
            logger.info(
                "Phase 2: %d/%d skill-gap contracts approved for session %s",
                len(approved),
                len(contracts),
                session_id[:8],
            )
        else:
            logger.debug(
                "Phase 2: %d skill-gap contracts processed, none approved (session %s)",
                len(contracts),
                session_id[:8],
            )
    except Exception:
        logger.debug("Phase 2 skill-gap background processing failed", exc_info=True)


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

        failed_events = await event_store.query_recent_events(event_type="error", limit=30)
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
                    len(approved),
                    len(high_heat),
                )
            else:
                logger.debug(
                    "Dream scan: %d contracts, %d approved, none auto-executable",
                    len(contracts),
                    len(approved),
                )
    except Exception:
        logger.debug("Dream scan background task failed", exc_info=True)


class CompletedState(FlowState):
    """Final state marking the end of the Plan-Act flow."""

    status = AgentStatus.COMPLETED

    def __init__(self, termination_reason: str = "") -> None:
        self._termination_reason = termination_reason

    async def execute(self, context: PlanActFlow, prompt: str) -> AsyncGenerator[AgentEvent, None]:

        if self._termination_reason:
            logger.info("Flow terminated: %s", self._termination_reason)

        # Computed before the plan is stamped, because the stamp depends on it.
        # `Plan.is_complete()` is `all(is_done())` and `is_done()` counts
        # FAILED, so "we stopped" and "it worked" were the same predicate here.
        failed_steps = context._plan.failed_steps() if context._plan else []

        if context._plan:
            terminal_plan_status = PlanStatus.FAILED if failed_steps else PlanStatus.COMPLETED
            context._plan = context._plan.model_copy(update={"status": terminal_plan_status})

            # ── AWM: induce workflow template from completed session ────
            if context._llm is not None and context._session is not None:
                try:
                    awm = context._get_awm()
                    if awm is not None:
                        template = await awm.induce(context._session)
                        if template is not None:
                            await awm.store(template)
                            logger.info(
                                "AWM: induced and stored workflow '%s' (%d steps) from session %s",
                                template.task_summary,
                                len(template.generalized_steps),
                                context._session.id[:8],
                            )
                except Exception as exc:
                    logger.debug("AWM: workflow induction skipped: %s", exc)
            plan_dump = context._plan.model_dump()
            # Emit and yield the SAME event object so event bus consumers
            # and flow callers see identical event IDs / timestamps.
            completed = PlanEvent(status=terminal_plan_status, plan=plan_dump)
            await context._emit(completed)
            yield completed

            # ── Save completed plan as template for reuse ────
            # Gated: see PLAN_TEMPLATE_CACHE_ENABLED in config/feature_flags.py.
            # `is_enabled` reads the flags module at call time, so a test can
            # set the attribute rather than reload the module.
            from weebot.config.feature_flags import is_enabled as _flag_enabled

            if (
                _flag_enabled("PLAN_TEMPLATE_CACHE_ENABLED")
                and context._plan
                and getattr(context, "_state_repo", None) is not None
            ):
                try:
                    from weebot.domain.services.plan_template_cache import compute_task_hash
                    from weebot.domain.models.plan_template import PlanTemplate
                    import json as _json
                    import uuid as _uuid

                    # Compute success score from step completion ratio.
                    #
                    # This counted `s.is_done()`, and `Step.is_done()` is
                    # `COMPLETED or FAILED` — so a plan in which every step
                    # failed scored **1.0** and was stored as a template for
                    # reuse. The failure was not merely reported as a success,
                    # it was learned from as one and would be preferentially
                    # retrieved for the next similar task.
                    total_steps = len(context._plan.steps)
                    succeeded_steps = sum(
                        1 for s in context._plan.steps if s.status == StepStatus.COMPLETED
                    )
                    score = round(succeeded_steps / total_steps, 2) if total_steps > 0 else 0.5

                    # `prompt` is "" here — CompletedState is never a run's
                    # first state — so this keyed every template it ever tried
                    # to write on `compute_task_hash("")`, with an empty
                    # description for the Jaccard fallback to match on. (D74.)
                    _task = task_text(context, prompt)
                    template = PlanTemplate(
                        template_id=str(_uuid.uuid4()),
                        task_hash=compute_task_hash(_task),
                        task_description=_task[:500],
                        plan_json=_json.dumps(context._plan.model_dump(), default=str),
                        success_score=score,
                    )
                    # One positional argument where the repository declares
                    # four. Every call raised TypeError into the handler below,
                    # which logged it at DEBUG — so the plan_templates table has
                    # never held a row. (D75.)
                    await context._state_repo.save_plan_template(
                        template.template_id,
                        template.task_hash,
                        template.task_description,
                        template.plan_json,
                        template.success_score,
                    )
                    logger.info(
                        "Saved plan template (hash=%s, score=%.2f) for session %s",
                        template.task_hash,
                        score,
                        context._session.id[:8],
                    )
                except Exception as exc:
                    # WARNING, not DEBUG. A save that cannot happen is worth
                    # one line in a normal log; at DEBUG this hid a TypeError
                    # on every completed run for the life of the feature.
                    logger.warning("Plan template save failed: %s", exc, exc_info=True)

        # A plan that ran out of runnable steps is not the same as one that
        # worked. `Plan.is_complete()` is `all(is_done())` and `is_done()`
        # counts FAILED, so every terminal plan reached here reporting success
        # — including one where nothing succeeded at all.
        #
        # `PlanStatus` has no failure member (created/updated/running/
        # completed), so the plan object above cannot say this; `SessionStatus`
        # can, and both the API and the web UI already understand `failed`.
        failed = failed_steps
        if failed:
            logger.warning(
                "Session %s finished with %d failed step(s): %s",
                context._session.id,
                len(failed),
                ", ".join(s.id for s in failed[:5]),
            )
        terminal = SessionStatus.COMPLETED if not failed else SessionStatus.FAILED
        context._session = context._session.set_status(terminal)
        if context._state_repo:
            await context._state_repo.save_session(context._session)
        context._step_execution_counts.clear()  # Reset for next run
        yield DoneEvent()

        # --- CQRS: score the trajectory if mediator is available ---
        if context._mediator:
            from weebot.application.cqrs.commands.trajectory_commands import ScoreTrajectoryCommand

            try:
                await context._mediator.send(
                    ScoreTrajectoryCommand(session_id=context._session.id, harness="direct_chat")
                )
            except Exception as exc:
                logger.warning(
                    "Trajectory scoring failed for session %s: %s", context._session.id, exc
                )

        # ── SessionStamp emission (Hallmark-inspired) ──────────────────
        try:
            from datetime import datetime
            from weebot.domain.models.stamp import SessionStamp, VerificationScores
            from weebot.application.services.plan_history import PlanHistory

            # Collect verification scores + gate failures from session context
            extra = getattr(context._session.context, "extra", {}) or {}
            scores_raw = extra.get("verification_scores", {})
            gate_failures = extra.get("gate_failures", [])
            # `verifying.py` has always computed this and written it here, and
            # nothing read it — `SessionStamp` forbids extra keys and had no
            # field for it, so a NOT_RUN marker could not reach the stamp even
            # if a consumer wanted it. An empty `gate_failures` means "no gate
            # failed", which is also what a gate that never ran produces.
            verification_status = str(extra.get("verification_status", "") or "")

            verif_scores = (
                VerificationScores(
                    correctness=scores_raw.get("correctness", 3),
                    completeness=scores_raw.get("completeness", 3),
                    specificity=scores_raw.get("specificity", 3),
                    restraint=scores_raw.get("restraint", 3),
                )
                if scores_raw
                else None
            )

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
                verification_status=verification_status,
                tool_calls=tool_count,
                errors=error_count,
                duration_ms=0,
                completed_at=datetime.now(UTC).isoformat(),
            )

            # Store stamp on session context
            context._session = context._session.model_copy(
                update={
                    "context": context._session.context.model_copy(
                        update={"stamp": stamp.model_dump()}
                    )
                }
            )
            logger.debug(
                "SessionStamp emitted for %s: %s", context._session.id, stamp.plan_fingerprint
            )
        except Exception:
            logger.debug("SessionStamp emission failed — non-blocking", exc_info=True)

        import time as _time

        _total_elapsed = _time.monotonic() - context._flow_started_at
        logger.info(
            "PlanActFlow completed for session %s in %.1fs", context._session.id, _total_elapsed
        )

        # ── Collect extra dict for TrustReport + RetentionReview + ProductContext ──
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
                        "context": context._session.context.model_copy(update={"extra": _extra})
                    }
                )
                logger.info(
                    "TrustReport session=%s band=%s confirmed=%d drift=%d regression=%d",
                    context._session.id,
                    trust_report.trust_band.value,
                    trust_report.confirmed_count,
                    trust_report.drift_count,
                    trust_report.regression_count,
                )
            except Exception:
                logger.debug("TrustReport failed — non-blocking", exc_info=True)

        # ── ProductDecisionEvent (product-mode Principle 7) ─────────────
        from weebot.config.feature_flags import PRODUCT_DECISION_LOG_ENABLED

        if PRODUCT_DECISION_LOG_ENABLED:
            _pc = _extra.get("product_context")
            if _pc:
                try:
                    _decision = ProductDecisionEvent(
                        title=f"Session {context._session.id[:8]}: {str(_pc.get('problem', 'unknown'))[:80]}",
                        problem=str(_pc.get("problem", "")),
                        why_now=str(_pc.get("why_now", "")),
                        choice=context._plan.title if context._plan else "unknown",
                        rationale=(
                            context._plan.message[:300]
                            if context._plan and context._plan.message
                            else ""
                        ),
                        reversibility=str(_pc.get("reversibility", "two-way")),
                        success_metric=str(_pc.get("success_metric", "")),
                        session_id=context._session.id,
                    )
                    await context._emit(_decision)
                    logger.info(
                        "ProductDecisionEvent emitted for session %s (reversibility: %s)",
                        context._session.id[:8],
                        _decision.reversibility,
                    )
                except Exception:
                    logger.debug(
                        "ProductDecisionEvent emission failed — non-blocking", exc_info=True
                    )

        # ── RetentionReview (Enhancement 5 — background, non-blocking) ──
        if getattr(context, "_retention_agent", None) is not None:
            _plan_for_retention = context._plan
            _trust_extra = _extra.get("trust_report", {})
            # Counts from events
            _tool_count_ret = sum(
                1 for e in context._session.events if getattr(e, "type", "") == "tool"
            )
            _error_count_ret = sum(
                1 for e in context._session.events if getattr(e, "type", "") == "error"
            )
            _session_summary = (
                f"{_plan_for_retention.title}: "
                + ", ".join(s.description for s in _plan_for_retention.steps[:5])
                if _plan_for_retention
                else "unknown"
            )
            # Owned, not orphaned. A bare `ensure_future` here is cancelled at
            # `asyncio.run()` teardown, so in the CLI this work never ran at
            # all — the Container and LLM adapters below were built and thrown
            # away — and any exception surfaced from the loop's default handler
            # instead of this module's logger. See BackgroundTasks.
            _background().spawn(
                _run_retention_review(
                    agent=context._retention_agent,
                    session_id=context._session.id,
                    session_summary=_session_summary,
                    trust_report=_trust_extra,
                    error_count=_error_count_ret,
                    tool_count=_tool_count_ret,
                ),
                name=f"retention-review:{context._session.id[:8]}",
            )

        # ── Phase 2: skill-gap processing (background, flag-gated) ────
        _gaps = getattr(getattr(context, "_executor", None), "_skill_gaps", [])
        if _gaps:
            _background().spawn(
                _run_skill_gap_processing(list(_gaps), context._session.id),
                name=f"skill-gaps:{context._session.id[:8]}",
            )

        # ── Dream scan background (Enhancement 8) ─────────────────────
        _background().spawn(_run_dream_scan(), name="dream-scan")

        # ── Hook: post_complete ────────────────────────────────────
        if getattr(context, "_hooks", None) is not None:
            from weebot.application.services.plan_history import PlanHistory

            _fp = PlanHistory.plan_fingerprint(context._plan) if context._plan else ""
            _tool_count = sum(
                1 for e in context._session.events if getattr(e, "type", "") == "tool"
            )
            _error_count = sum(
                1 for e in context._session.events if getattr(e, "type", "") == "error"
            )
            await context._hooks.execute_hooks(
                "post_complete",
                {
                    "session_id": context._session.id,
                    "plan": context._plan,
                    "tool_count": _tool_count,
                    "error_count": _error_count,
                    "total_elapsed_ms": _total_elapsed * 1000,
                    "plan_fingerprint": _fp,
                },
            )

        # Reset to IDLE for potential future runs in same session object
        # but the run loop in PlanActFlow will pick this up.
