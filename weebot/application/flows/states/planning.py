"""Planning state for Plan-Act flow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from collections.abc import AsyncGenerator

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.domain.services.session_lessons import (
    journal_lessons,
    project_key,
    session_lessons,
)
from weebot.application.flows.states.base import (
    AgentStatus,
    FlowState,
    StateId,
    new_state,
    next_state_after_plan,
    register_state,
    task_text,
)
from weebot.domain.models.event import AgentEvent, PlanEvent
from weebot.domain.models.plan import Plan, PlanStatus

logger = logging.getLogger(__name__)


def _infer_domain(prompt: str) -> str:
    """Quick heuristic to infer a task domain from the prompt text.

    Used by strategy transfer to find relevant prior experience.
    Checks more specific domains first to avoid false matches.
    """
    lo = prompt.lower()
    # Check robotics before coding — "reward function" is robotics, not coding
    if any(
        kw in lo
        for kw in (
            "robot",
            "reward function",
            "reinforcement learning",
            "quadruped",
            "rl ",
            "physics sim",
        )
    ):
        return "robotics"
    if any(
        kw in lo
        for kw in (
            "code",
            "refactor",
            "debug",
            "implement",
            "python",
            "javascript",
            "typescript",
            "html",
            "css",
            "api endpoint",
            "rest api",
        )
    ):
        return "coding"
    if any(kw in lo for kw in ("review", "paper", "conference", "submission", "accept", "reject")):
        return "review"
    if any(kw in lo for kw in ("math", "proof", "theorem", "olympiad", "imo", "grade")):
        return "math"
    if any(kw in lo for kw in ("browser", "login", "navigate", "click", "fill", "form", "scrape")):
        return "automation"
    if any(kw in lo for kw in ("function", "class", "script", "deploy")):
        return "coding"
    return "general"


@register_state(StateId.PLANNING)
class PlanningState(FlowState):
    """Handles the creation of the initial execution plan."""

    status = AgentStatus.PLANNING

    async def execute(self, context: PlanActFlow, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.agents.planner import PlannerAgent
        from weebot.domain.models.event import ErrorEvent as EE

        # Apply context-aware model switching before any execution
        new_model = context._maybe_switch_model_for_context()
        if new_model:
            context._update_agents_with_model(new_model)

        # --- CQRS: execute plan creation through mediator (REQUIRED) ---
        if context._mediator is None:
            yield EE(
                error=(
                    "PlanningState requires a Mediator to be configured on PlanActFlow. "
                    "Construct PlanActFlow with mediator=container.get(Mediator) or "
                    "build it through container.get(\"create_flow\")."
                )
            )
            return

        # ── Prompt fallback ────────────────────────────────────────────
        # When a pre-planning gate (ProductGateState) yields events before
        # transitioning here, the run loop hands this state "". This fallback
        # was written inline here first; `task_text` is the same rule, now
        # shared with the five other states that were still reading "". (D74.)
        if not prompt.strip():
            prompt = task_text(context, prompt)
            logger.debug("PlanningState prompt was empty — using fallback: %.80s", prompt)

        # ── Intent disambiguation gate (Enhancement 2 — S2 fix) ──────────────
        # Skip if this is a short continuation like "yes" / "proceed".
        # IntentReviewService.review() times out after WEEBOT_INTENT_REVIEW_TIMEOUT_S
        # (default 30 s) and fails open.
        _is_continuation = len(prompt.split()) < 6 and prompt.strip().lower() in {
            "yes",
            "ok",
            "proceed",
            "continue",
            "approve",
            "go ahead",
            "y",
            "go",
            "do it",
            "run",
            "start",
            "lgtm",
        }
        if not _is_continuation and not context._session.context.get("_intent_reviewed"):
            try:
                from weebot.application.services.intent_review_service import IntentReviewService
                from weebot.domain.models.idea_contract import IdeaContract, IdeaSource
                from weebot.domain.models.intent_review import IntentVerdict

                _contract = IdeaContract(
                    title=prompt[:80], prompt=prompt, source=IdeaSource.USER_PROMPT
                )
                _review = await IntentReviewService(context._llm).review(_contract)

                if _review.verdict == IntentVerdict.NOT_READY and _review.clarification_needed:
                    _new_extra = {**context._session.context.extra, "_intent_reviewed": True}
                    _new_ctx = context._session.context.model_copy(update={"extra": _new_extra})
                    context._session = context._session.model_copy(update={"context": _new_ctx})
                    # A durable pause: WAITING, persisted, before the yield. A
                    # bare WaitForUserEvent left the session pending, and the
                    # user's answer failed with "is not waiting".
                    from weebot.application.flows.collaborators.user_pause import (
                        pause_for_user,
                    )

                    yield await pause_for_user(
                        context,
                        "\n".join(
                            f"{i+1}. {q}" for i, q in enumerate(_review.clarification_needed[:3])
                        ),
                    )
                    return

                if _review.verdict == IntentVerdict.BLOCKED:
                    yield EE(error=f"Request blocked by intent review: {_review.reasoning}")
                    return

            except Exception as _ie_exc:
                logger.debug("Intent review skipped: %s", _ie_exc)

        # Mark as reviewed so resume doesn't re-trigger
        _new_extra = {**context._session.context.extra, "_intent_reviewed": True}
        _new_ctx = context._session.context.model_copy(update={"extra": _new_extra})
        context._session = context._session.model_copy(update={"context": _new_ctx})
        # ──────────────────────────────────────────────────────────────────────

        # ── Plan modification request (Enhancement 4) ────────────────────────
        # When the user rejected a plan during review and asked for changes,
        # the modification request is stored in session context extra.
        _mod_request = context._session.context.get("_plan_modification_request", "")
        if _mod_request:
            prompt = f"{prompt}\n\n[User requested modification to prior plan: {_mod_request}]"
            # Clear so it doesn't persist to future re-plans
            _new_extra_mod = {**context._session.context.extra, "_plan_modification_request": ""}
            _new_ctx_mod = context._session.context.model_copy(update={"extra": _new_extra_mod})
            context._session = context._session.model_copy(update={"context": _new_ctx_mod})
        # ─────────────────────────────────────────────────────────────────────

        # ── Misalignment journal meta_notes (Enhancement 5) ─────────────────
        _avoidance_notes: list[str] = []
        _journal = getattr(context, "_misalignment_journal", None)
        if _journal is not None:
            _project_path = project_key(context._session.context.get("working_dir"))
            try:
                _recent = await _journal.get_recent(_project_path, limit=10)
                _avoidance_notes += journal_lessons(_recent, context._session.context.meta_notes)
                _recent = [e for e in _recent if e.symptom != "session_lesson"][:3]
                for _entry in _recent:
                    if _entry.symptom == "constraint_violation" and _entry.constraint_text:
                        _avoidance_notes.append(
                            f"Previously violated: '{_entry.constraint_text}' "
                            f"(step: '{_entry.step_description}'). Avoid this pattern."
                        )
                    elif _entry.symptom == "user_correction" and _entry.correction_text:
                        _avoidance_notes.append(
                            f"User correction from prior session: '{_entry.correction_text[:120]}'"
                        )
            except Exception:
                pass  # journal read failures must never block planning
        # ── Lessons MetaAnalysisState stored on this session ────────────────
        # They were written (Session.add_meta_note) but never read back. They go first:
        # the planner keeps only the last 5 notes, and a recorded violation must outlast them.
        _avoidance_notes = session_lessons(context._session.context.meta_notes) + _avoidance_notes
        # ─────────────────────────────────────────────────────────────────────

        import time as _time
        from weebot.application.cqrs.commands import CreatePlanCommand
        from weebot.config.model_refs import MODEL_BUDGET

        # Workflow hints from similar past runs go to the FIRST plan, not only the replanner.
        _awm_hints_used = await _awm_hints(context, prompt)
        _plan_t0 = _time.monotonic()
        cmd_result = await context._mediator.send(
            CreatePlanCommand(
                session_id=context._session.id,
                prompt=prompt,
                model=context._model or MODEL_BUDGET,
                context=context._session.context.model_dump(mode="json"),
                meta_notes=_avoidance_notes,
                awm_hints=_awm_hints_used or [],
            )
        )
        _plan_elapsed = _time.monotonic() - _plan_t0
        if not cmd_result.success:
            yield EE(error=f"Plan creation rejected: {cmd_result.error}")
            # Left RUNNING, the flow loop re-entered this state at once, up to max_iterations
            # times: 47+ identical 402 "insufficient credits" errors and a session stuck forever.
            from weebot.domain.models.session import SessionStatus

            context._session = context._session.set_status(SessionStatus.FAILED)
            return

        # Consume events from the mediator result using shared reconstructor.
        from weebot.application.cqrs.event_reconstructor import reconstruct_events

        for event in reconstruct_events(cmd_result.data.get("events", [])):
            await context._emit(event)
            yield event
            if isinstance(event, PlanEvent) and event.status == PlanStatus.CREATED:
                context._plan = Plan.model_validate(event.plan)
                logger.info(
                    "Plan created with %d steps in %.1fs", len(context._plan.steps), _plan_elapsed
                )
                # Hook: post_plan_created
                if getattr(context, "_hooks", None) is not None:
                    await context._hooks.execute_hooks(
                        "post_plan_created",
                        {
                            "session_id": context._session.id,
                            "plan": context._plan,
                            "step_count": len(context._plan.steps),
                            "elapsed_ms": _plan_elapsed * 1000,
                        },
                    )

        # Also check for plan in result top-level
        if context._plan is None and cmd_result.data.get("plan"):
            context._plan = Plan.model_validate(cmd_result.data["plan"])

        if context._plan is None or len(context._plan.steps) == 0:
            logger.info("No steps in plan, transitioning to SUMMARIZING")

            context.set_state(new_state(StateId.SUMMARIZING))
        else:
            context._snapshot_plan()
            # --- DPPM: parallel planning for complex tasks ---
            from weebot.application.agents.parallel_planner import ParallelPlanner

            _use_dppm = context._planning_mode == "dppm" or (
                context._planning_mode == "auto" and ParallelPlanner.is_complex_task(prompt)
            )
            if _use_dppm and context._llm is not None:
                try:
                    from weebot.application.services.plan_merger import PlanMerger

                    dppm = ParallelPlanner(llm=context._llm)
                    merger = PlanMerger(llm=context._llm)
                    candidates = await dppm.generate(prompt, num_alternatives=2)
                    if candidates:
                        plan = await merger.merge(candidates, prompt)
                        if plan is not None:
                            # Persist before adopting: the resume after plan review
                            # restores the last PlanEvent, so without this event the
                            # pre-DPPM plan ran instead of the one reviewed (F36).
                            dppm_event = PlanEvent(
                                status=PlanStatus.UPDATED, plan=plan.model_dump(mode="json")
                            )
                            await context._emit(dppm_event)
                            context._plan = plan
                            yield dppm_event
                            logger.info(
                                "DPPM: generated plan with %d steps from %d candidates",
                                len(plan.steps),
                                len(candidates),
                            )
                except Exception as exc:
                    logger.warning("DPPM planning failed, falling back to sequential: %s", exc)

            awm_hints = _awm_hints_used
            # Rehydrate planner with latest facts before executing
            context._planner = PlannerAgent(
                llm=context._llm,
                event_bus=context._event_bus,
                model=context._model,
                skill_prompt=context._skill_prompt,
                facts=context._session.get_facts(),
                awm_hints=awm_hints,
            )
            # Transition to CritiquingState if a critic is available
            if context._plan_critic is not None:

                context.set_state(new_state(StateId.CRITIQUING, critic=context._plan_critic))
            else:

                context.set_state(next_state_after_plan())

async def _awm_hints(context, prompt: str) -> list[str] | None:
    """Generalized steps from the most successful similar past workflow, if any."""
    if context._llm is None:
        return None
    try:
        awm = context._get_awm()
        if awm is None:
            return None
        templates = await awm.query(prompt, max_results=2)
        if not templates:
            return None
        best = max(templates, key=lambda t: t.success_rate)
        if not best.generalized_steps:
            return None
        logger.info(
            "AWM: injected %d workflow hints from '%s' (%.0f%% success rate)",
            len(best.generalized_steps),
            best.task_summary,
            best.success_rate * 100,
        )
        return list(best.generalized_steps)
    except Exception as exc:
        logger.debug("AWM: workflow query skipped: %s", exc)
        return None
