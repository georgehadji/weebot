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
            # Rehydrate planner with latest facts before executing
            context._planner = PlannerAgent(
                llm=context._llm,
                event_bus=context._event_bus,
                model=context._model,
                skill_prompt=context._skill_prompt,
                facts=context._session.get_facts(),
                episodic_memory=context._episodic_memory,
            )
            # Transition to CritiquingState if a critic is available
            if context._plan_critic is not None:
                from weebot.application.flows.states.critiquing import CritiquingState
                context.set_state(CritiquingState(critic=context._plan_critic))
            else:
                context.set_state(ExecutingState())
