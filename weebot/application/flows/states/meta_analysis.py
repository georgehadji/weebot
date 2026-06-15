"""MetaAnalysisState — post-summary trajectory critique (HyperAgents Enhancement 1).

After the SummarizingState produces a final summary, this state runs a
cheap meta-critique of the full trajectory.  The resulting meta-notes are
stored in session.context.meta_notes and injected into future planning
cycles so the planner learns from past successes and failures.
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import FlowState
from weebot.domain.models.event import AgentEvent, PlanEvent, StepStatus as EventStepStatus

logger = logging.getLogger(__name__)


class MetaAnalysisState(FlowState):
    """Post-summary meta-critique using a budget-tier LLM.

    Extracts what worked, what failed, and one concrete strategy change
    from the completed trajectory.  Stores results as meta_notes on the
    session for future planner injection.

    Failures in meta-analysis are logged but never block completion —
    the flow always transitions to CompletedState regardless.
    """

    # No status enum value yet — use SUMMARIZING as a reasonable neighbor.
    # A dedicated META_ANALYZING value can be added to AgentStatus later.
    status = None  # Intentionally None — state transition is transparent

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.completed import CompletedState

        plan = context._plan
        session = context._session

        # ── Gather trajectory data ──
        task_description = session.context.original_task or prompt or "(no task)"
        plan_summary = (
            f"{plan.title}: {plan.message}" if plan else "(no plan)"
        )

        step_results: list[tuple[str, str]] = []
        failures: list[str] = []
        tool_count: int = 0

        for event in session.events:
            from weebot.domain.models.event import StepEvent, ErrorEvent, ToolEvent
            if isinstance(event, StepEvent) and event.status == EventStepStatus.COMPLETED:
                step_results.append((event.step_id, event.description or ""))
            elif isinstance(event, ErrorEvent) and event.error:
                failures.append(event.error)
            elif isinstance(event, ToolEvent):
                tool_count += 1

        # ── Run meta-critique (best-effort, never blocks) ──
        try:
            from weebot.application.services.meta_critic import MetaCritic

            critic = MetaCritic(llm=context._llm)
            result = await critic.critique(
                task_description=task_description,
                plan_summary=plan_summary,
                step_results=step_results,
                failures=failures,
                tool_count=tool_count,
            )

            if result.meta_note and result.meta_note != "No actionable insights":
                context._session = context._session.add_meta_note(result.meta_note)
                context._log.info(
                    "Meta-analysis produced note: %s",
                    result.meta_note[:120],
                )
            else:
                context._log.debug("Meta-analysis produced no actionable insights")
        except Exception as exc:
            context._log.warning("Meta-analysis failed (non-blocking): %s", exc)

        # ── Phase 1: live skill distillation (flag-guarded) ──────────
        await _maybe_distil_skill(context, step_results, failures, tool_count)

        # ── Transition to VerifyingState (CoVe) → CompletedState ──
        from weebot.application.flows.states.verifying import VerifyingState
        context.set_state(VerifyingState())


async def _maybe_distil_skill(
    context: "PlanActFlow",
    step_results: list[tuple[str, str]],
    failures: list[str],
    tool_count: int,
) -> None:
    """Run live skill distillation if the feature flag is enabled.

    Best-effort — any exception is logged and swallowed so it never
    blocks the flow.  The distiller is flag-gated; when the flag is off
    DI returns a _NoOpDistiller and this function is a no-op.
    """
    from weebot.config.feature_flags import LIVE_SKILL_DISTILLATION_ENABLED

    distiller = getattr(context, "_skill_distiller", None)
    if distiller is None or not LIVE_SKILL_DISTILLATION_ENABLED:
        return

    session = context._session
    try:
        # Build a compact trajectory text for the distiller
        trajectory_lines: list[str] = []
        task = session.context.original_task or "(no task)"
        trajectory_lines.append(f"Task: {task}")
        trajectory_lines.append(f"Steps completed: {len(step_results)}, tool calls: {tool_count}")
        if failures:
            trajectory_lines.append(f"Failures: {'; '.join(failures[:3])}")
        for step_id, desc in step_results:
            trajectory_lines.append(f"  - [{step_id}] {desc}")
        trajectory_text = "\n".join(trajectory_lines)

        skill = await distiller.analyze_session(
            session_id=session.id,
            trajectory=trajectory_text,
        )
        if skill is not None:
            # Publish lifecycle event for observability
            try:
                from weebot.domain.models.event import SkillDistilled
                ev = SkillDistilled(
                    session_id=session.id,
                    skill_name=skill.name,
                    content_preview=skill.content[:200],
                    origin=skill.metadata.provenance.origin,
                )
                if context._event_bus is not None:
                    await context._event_bus.publish(ev)
            except Exception:
                pass  # observability failure must never block flow
            context._log.info(
                "Phase 1: distilled quarantined skill '%s' from session %s",
                skill.name, session.id[:8],
            )
    except Exception as exc:
        context._log.warning("Phase 1 skill distillation failed (non-blocking): %s", exc)
