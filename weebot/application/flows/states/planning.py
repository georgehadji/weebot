"""Planning state for Plan-Act flow."""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState
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
    if any(kw in lo for kw in ("robot", "reward function", "reinforcement learning", "quadruped", "rl ", "physics sim")):
        return "robotics"
    if any(kw in lo for kw in ("code", "refactor", "debug", "implement", "python", "javascript", "typescript", "html", "css", "api endpoint", "rest api")):
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


class PlanningState(FlowState):
    """Handles the creation of the initial execution plan."""
    status = AgentStatus.PLANNING

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.plan_act_flow import AgentStatus
        from weebot.application.flows.states.executing import ExecutingState
        from weebot.application.flows.states.summarizing import SummarizingState
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
                    "use container.build_agent_runner()."
                )
            )
            return

        # ── Prompt fallback: when a pre-planning gate (ProductGateState)
        # yields events before transitioning here, the run-loop's
        # prompt_consumed flag starves us of the task prompt.  Fall back
        # to original_task or last_prompt stored in the session context.
        if not prompt.strip():
            prompt = (
                context._session.context.get("_original_task", "")
                or context._session.context.get("last_prompt", "")
            )
            logger.debug("PlanningState prompt was empty — using fallback: %.80s", prompt)

        # ── Intent disambiguation gate (Enhancement 2 — S2 fix) ──────────────
        # Skip if this is a short continuation like "yes" / "proceed".
        # IntentReviewService.review() has a 5s timeout and fails open.
        _is_continuation = (
            len(prompt.split()) < 6
            and prompt.strip().lower() in {
                "yes", "ok", "proceed", "continue", "approve", "go ahead",
                "y", "go", "do it", "run", "start", "lgtm",
            }
        )
        if not _is_continuation and not context._session.context.get("_intent_reviewed"):
            try:
                from weebot.application.services.intent_review_service import IntentReviewService
                from weebot.domain.models.idea_contract import IdeaContract, IdeaSource
                from weebot.domain.models.intent_review import IntentVerdict
                from weebot.domain.models.event import WaitForUserEvent

                _contract = IdeaContract(
                    title=prompt[:80],
                    prompt=prompt,
                    source=IdeaSource.USER_PROMPT,
                )
                _review = await IntentReviewService(context._llm).review(_contract)

                if _review.verdict == IntentVerdict.NOT_READY and _review.clarification_needed:
                    _new_extra = {**context._session.context.extra, "_intent_reviewed": True}
                    _new_ctx = context._session.context.model_copy(update={"extra": _new_extra})
                    context._session = context._session.model_copy(update={"context": _new_ctx})
                    yield WaitForUserEvent(
                        question="\n".join(
                            f"{i+1}. {q}"
                            for i, q in enumerate(_review.clarification_needed[:3])
                        )
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
            _project_path = context._session.context.get("working_dir", "")
            try:
                _recent = await _journal.get_recent(_project_path, limit=3)
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
        # ─────────────────────────────────────────────────────────────────────

        import time as _time
        from weebot.application.cqrs.commands import CreatePlanCommand
        from weebot.config.model_refs import MODEL_BUDGET
        _plan_t0 = _time.monotonic()
        cmd_result = await context._mediator.send(
            CreatePlanCommand(
                session_id=context._session.id,
                prompt=prompt,
                model=context._model or MODEL_BUDGET,
                context=context._session.context.model_dump(mode="json"),
                meta_notes=_avoidance_notes,
            )
        )
        _plan_elapsed = _time.monotonic() - _plan_t0
        if not cmd_result.success:
            yield EE(error=f"Plan creation rejected: {cmd_result.error}")
            return

        # Consume events from the mediator result using shared reconstructor.
        from weebot.application.cqrs.event_reconstructor import reconstruct_events
        for event in reconstruct_events(cmd_result.data.get("events", [])):
            await context._emit(event)
            yield event
            if isinstance(event, PlanEvent) and event.status == PlanStatus.CREATED:
                context._plan = Plan.model_validate(event.plan)
                logger.info("Plan created with %d steps in %.1fs",
                            len(context._plan.steps), _plan_elapsed)
                # Hook: post_plan_created
                if getattr(context, "_hooks", None) is not None:
                    await context._hooks.execute_hooks("post_plan_created", {
                        "session_id": context._session.id,
                        "plan": context._plan,
                        "step_count": len(context._plan.steps),
                        "elapsed_ms": _plan_elapsed * 1000,
                    })

        # Also check for plan in result top-level
        if context._plan is None and cmd_result.data.get("plan"):
            context._plan = Plan.model_validate(cmd_result.data["plan"])

        if context._plan is None or len(context._plan.steps) == 0:
            logger.info("No steps in plan, transitioning to SUMMARIZING")
            from weebot.application.flows.states.summarizing import SummarizingState
            context.set_state(SummarizingState())
        else:
            context._snapshot_plan()
            # --- DPPM: parallel planning for complex tasks ---
            _use_dppm = (
                context._planning_mode == "dppm"
                or (context._planning_mode == "auto"
                    and ParallelPlanner.is_complex_task(prompt))
            )
            if _use_dppm and context._llm is not None:
                try:
                    from weebot.application.agents.parallel_planner import ParallelPlanner
                    from weebot.application.services.plan_merger import PlanMerger

                    dppm = ParallelPlanner(llm=context._llm)
                    merger = PlanMerger(llm=context._llm)
                    candidates = await dppm.generate(prompt, num_alternatives=2)
                    if candidates:
                        plan = await merger.merge(candidates, prompt)
                        if plan is not None:
                            context._plan = plan
                            logger.info(
                                "DPPM: generated plan with %d steps from %d candidates",
                                len(plan.steps), len(candidates),
                            )
                except Exception as exc:
                    logger.warning("DPPM planning failed, falling back to sequential: %s", exc)

            # --- AWM: retrieve workflow hints from similar past sessions ---
            awm_hints = None
            if context._llm is not None:
                try:
                    awm = context._get_awm()
                    if awm is not None:
                        templates = await awm.query(prompt, max_results=2)
                        if templates:
                            # Pick the template with the highest success rate
                            best = max(templates, key=lambda t: t.success_rate)
                            if best.generalized_steps:
                                awm_hints = best.generalized_steps
                                logger.info(
                                    "AWM: injected %d workflow hints from '%s' (%.0f%% success rate)",
                                    len(awm_hints), best.task_summary, best.success_rate * 100,
                                )
                except Exception as exc:
                    logger.debug("AWM: workflow query skipped: %s", exc)
            # Rehydrate planner with latest facts before executing
            context._planner = PlannerAgent(
                llm=context._llm,
                event_bus=context._event_bus,
                model=context._model,
                skill_prompt=context._skill_prompt,
                facts=context._session.get_facts(),
                episodic_memory=context._episodic_memory,
                awm_hints=awm_hints,
            )
            # Transition to CritiquingState if a critic is available
            if context._plan_critic is not None:
                from weebot.application.flows.states.critiquing import CritiquingState
                context.set_state(CritiquingState(critic=context._plan_critic))
            else:
                from weebot.application.flows.states.plan_review import next_state_after_plan
                context.set_state(next_state_after_plan())
