"""Critiquing state for Plan-Act flow — validates plans before execution.

Inserts between PlanningState and ExecutingState:
- overall_confidence >= 0.8 → proceed to ExecutingState
- 0.5 <= overall_confidence < 0.8 → proceed with warnings injected into executor prompt
- overall_confidence < 0.5 → send back to PlanningState with critique context
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.application.services.plan_critic import PlanCriticService
from weebot.domain.models.event import AgentEvent, ErrorEvent
from weebot.domain.models.plan import PlanCritique

logger = logging.getLogger(__name__)


class ConfidentThresholds:
    """Confidence thresholds for plan critique verdicts."""
    REVISE_THRESHOLD = 0.5
    WARN_THRESHOLD = 0.8


class CritiquingState(FlowState):
    """Validates a plan before allowing execution to proceed."""
    status = AgentStatus.PLANNING  # Reuses PLANNING status to avoid adding new enum values

    def __init__(self, critic: PlanCriticService | None = None) -> None:
        """Initialize critiquing state.

        Args:
            critic: Optional PlanCriticService. If None, the state
                    falls through to ExecutingState without critique.
        """
        self._critic = critic

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.executing import ExecutingState
        from weebot.application.flows.states.planning import PlanningState

        if self._critic is None:
            logger.info("No plan critic available — proceeding to execution")
            context.set_state(ExecutingState())
            return

        if context._plan is None:
            yield ErrorEvent(error="No plan available for critique")
            context.set_state(ExecutingState())
            return

        logger.info(
            "Critiquing plan '%s' with %d steps",
            context._plan.title, len(context._plan.steps),
        )

        # Reset critique from previous cycle
        context._plan_critique = None

        # Build critique context
        critique_context = {
            "task": prompt,
            "tools": [t.name for t in context._tools] if hasattr(context._tools, "__iter__") else [],
        }

        # Run the critic
        critique: PlanCritique = await self._critic.critique(
            context._plan, critique_context,
        )

        logger.info(
            "Plan critique verdict: %s (confidence: %.2f, flaws: %d)",
            critique.verdict, critique.overall_confidence, len(critique.flaws),
        )

        # ── Phase 5: Override thresholds from task_preset if provided ──
        _warn = ConfidentThresholds.WARN_THRESHOLD
        _revise = ConfidentThresholds.REVISE_THRESHOLD
        _preset = getattr(context, "_task_preset", None)
        if _preset is not None:
            _warn = getattr(_preset, "critique_warn_threshold", _warn)
            _revise = getattr(_preset, "critique_revise_threshold", _revise)

        # ── Route based on confidence ──
        if critique.overall_confidence >= _warn:
            # High confidence — proceed to pre-mortem then execution
            logger.info("Plan approved with high confidence")
            from weebot.application.flows.states.premortem import PremortmState
            context.set_state(PremortmState())

        elif critique.overall_confidence >= _revise:
            # Medium confidence — proceed but inject warnings
            logger.info(
                "Plan approved with warnings (%d flaws)",
                len(critique.flaws),
            )
            # Store critique on the flow for executor prompt injection
            context._plan_critique = critique
            from weebot.application.flows.states.premortem import PremortmState
            context.set_state(PremortmState())

        else:
            # Low confidence — send back to planning
            logger.info(
                "Plan rejected (confidence: %.2f). Sending back to planner with critique.",
                critique.overall_confidence,
            )
            # Store critique on the flow for planner context
            context._plan_critique = critique
            context.set_state(PlanningState())

        # Yield critique as a thought event for observability
        from weebot.domain.models.event import ThoughtEvent
        yield ThoughtEvent(
            step_id="critique",
            thought=(
                f"**Plan Critique** — Verdict: {critique.verdict}, "
                f"Confidence: {critique.overall_confidence:.2f}\n\n"
                + ("**Flaws:**\n" + "\n".join(f"- {f}" for f in critique.flaws) if critique.flaws else "")
                + ("\n\n**Suggestions:**\n" + "\n".join(f"- {s}" for s in critique.suggestions) if critique.suggestions else "")
            ),
        )
