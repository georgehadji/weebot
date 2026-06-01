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

        # --- CQRS: execute plan creation through mediator ---
        if context._mediator:
            from weebot.application.cqrs.commands import CreatePlanCommand
            cmd_result = await context._mediator.send(
                CreatePlanCommand(
                    session_id=context._session.id,
                    prompt=prompt,
                    model=context._model or "default",
                    context=context._session.context,
                )
            )
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
                    logger.info("Plan created with %d steps", len(context._plan.steps))

            # Also check for plan in result top-level
            if context._plan is None and cmd_result.data.get("plan"):
                context._plan = Plan.model_validate(cmd_result.data["plan"])
        else:
            # Fallback: direct agent call (no mediator available)
            import warnings
            warnings.warn(
                "PlanningState: no mediator, using direct planner call. "
                "Pipeline behaviors (logging, validation, telemetry) will NOT fire.",
                DeprecationWarning, stacklevel=2,
            )
            async for event in context._planner.create_plan(prompt):
                await context._emit(event)
                yield event
                if isinstance(event, PlanEvent) and event.status == PlanStatus.CREATED:
                    context._plan = Plan.model_validate(event.plan)
                    logger.info("Plan created with %d steps", len(context._plan.steps))

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
            context.set_state(ExecutingState())
