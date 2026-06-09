"""PremortmState — prospective failure analysis before execution.

Sits between CritiquingState and ExecutingState when enabled.
Injects risk notes into the plan; never blocks execution.

Enabled by: plan step count >= PREMORTEM_MIN_STEPS (default 3)
OR task_preset.enable_premortem == True.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.domain.models.event import AgentEvent, ThoughtEvent

logger = logging.getLogger(__name__)

PREMORTEM_MIN_STEPS = 3


class PremortmState(FlowState):
    """Runs a pre-mortem analysis and injects risk notes into the plan."""

    status = AgentStatus.PLANNING  # Planning sub-phase — reuses existing status

    async def execute(
        self, context: "PlanActFlow", prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.executing import ExecutingState
        from weebot.application.services.premortem_analyzer import PremortmAnalyzer

        plan = context._plan
        # Check task_preset.enable_premortem first; fall back to step-count heuristic
        _enable = getattr(getattr(context, "_task_preset", None), "enable_premortem", None)
        if _enable is False:
            logger.debug("Pre-mortem skipped: disabled by task preset")
            context.set_state(ExecutingState())
            return
        if _enable is None and (plan is None or len(plan.steps) < PREMORTEM_MIN_STEPS):
            logger.debug(
                "Pre-mortem skipped: plan has %d steps (min %d)",
                len(plan.steps) if plan else 0, PREMORTEM_MIN_STEPS,
            )
            context.set_state(ExecutingState())
            return

        analyzer = PremortmAnalyzer(llm=context._llm)
        risks = await analyzer.analyze(plan, prompt)

        if risks:
            # Inject risk notes into plan message so PlannerAgent / executor can see them
            risk_block = "\n".join(f"⚠ {r}" for r in risks)
            context._plan = plan.model_copy(
                update={
                    "message": (
                        f"{plan.message or ''}\n\n"
                        f"[Pre-mortem risks]\n{risk_block}"
                    ).strip()
                }
            )
            logger.info("Pre-mortem injected %d risks into plan", len(risks))

            yield ThoughtEvent(
                step_id="premortem",
                thought=(
                    f"**Pre-Mortem Analysis** — {len(risks)} potential failure modes:\n\n"
                    + "\n".join(f"- {r}" for r in risks)
                ),
            )
        else:
            logger.debug("Pre-mortem produced no risks")

        context.set_state(ExecutingState())
