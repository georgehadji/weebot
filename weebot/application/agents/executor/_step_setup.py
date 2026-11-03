"""Per-step setup for `ExecutorAgent.execute_step` (WB-06, phase 4.2).

`execute_step` was 527 lines. The first ~130 were setup: reset the ephemeral state, open
the tracing span, fetch the user profile, assemble the system prompt from five optional
contributors, then seed the conversation buffer with the plan's context.

It is split in two rather than one function because `yield StepEvent(...)` lands in the
middle of it -- the caller emits STARTED once the step's context is bound and *before*
the prompt is built. Keeping that seam visible is the point; folding it into a single
"prepare" would hide where the first event goes out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from weebot.application.agents.executor._prompt_builder import (
    build_step_context,
    build_system_blocks,
)
from weebot.application.models.prompt_layout import (
    PromptLayoutBuilder,
    system_sha,
    tools_sha,
)

MAX_FROZEN_SYSTEMS = 32
"""Session/scope entries of the system prompt kept before the oldest is dropped."""

if TYPE_CHECKING:
    from weebot.application.agents.executor._base import ExecutorAgent
    from weebot.domain.models.plan import Plan, Step

logger = logging.getLogger(__name__)


@dataclass
class StepPrime:
    """What the caller needs after the step's context is bound."""

    tool_note: str
    span: Any | None


def prime_step(
    executor: ExecutorAgent, step: Step, session_id: str, plan: Plan | None = None
) -> StepPrime:
    """Bind the step's identity and open its tracing span.

    Everything here must happen before the first event is emitted, because the approval
    scope and the audit records read the session and step from the executor.
    """
    span = None
    if executor._tracing_port is not None:
        from weebot.config.feature_flags import is_enabled

        if is_enabled("OTEL_TRACING_ENABLED"):
            span = executor._tracing_port.start_span("executor_step")
            span.set_attribute("step.id", step.id)
            span.set_attribute("step.description", step.description[:200])

    executor._current_step_id = step.id
    executor._current_session_id = session_id or getattr(
        executor, "_current_session_id", "unknown"
    )
    # The approval scope and audit records read the session from here; it was never set,
    # so Flow pause denied every web approval (B2c).
    executor._tool_executor.set_step_context(step.id, session_id, step.description or "")
    tool_note = executor._scope_tools_for(step, plan)
    return StepPrime(tool_note=tool_note, span=span)


async def build_step_prompts(
    executor: ExecutorAgent, plan: Plan, step: Step, user_input: str | None, tool_note: str = ""
) -> None:
    """Assemble the system prompt and seed the conversation buffer for this step.

    The system prompt is the session's stable part only (H10): it is built at the first
    step of a session and scope and reused. What changes with the step (retrieved skills,
    behavioural rules, the output root, the tool note) leads the step's first user message.
    """
    step_scope = getattr(step, "context_scope", None)
    scope_value = step_scope.value if step_scope is not None else "full"
    static, session = await _frozen_system(executor, scope_value)

    retrieval_scores: list[float] = []
    step_text = await build_step_context(
        step.description,
        context_scope=scope_value,
        skill_prompt=executor._skill_prompt,
        skill_retriever=executor._skill_retriever,
        behavioral_learner=executor._behavioral_learner,
        skills_used=executor._skills_used,
        retrieval_scores=retrieval_scores,
    )
    if retrieval_scores:
        record_skill_gap(executor, step.description, retrieval_scores[0])

    # Inject OUTPUT_ROOT so tools resolve paths consistently
    from weebot.core.output_path import output_path as _op

    step_context = (
        "## STEP CONTEXT"
        + step_text
        + f"\n\nOUTPUT_ROOT = {_op('Output')}"
        "\nALL file writes MUST use this absolute path prefix. "
        'Example: Set-Content -Path "{OUTPUT_ROOT}/refactor/file.md" -Value ...'
        + tool_note
    )
    tools = executor._tools.to_params() if executor._tools else []
    layout = PromptLayoutBuilder().static(static).session(session).step(step_context).build(tools)
    executor._system_prompt = layout.system
    _record_prefix(executor, layout.system, tools, layout.prefix_sha)

    _seed_conversation(executor, plan, step, user_input, preamble=layout.step_context)


async def _frozen_system(executor: ExecutorAgent, scope_value: str) -> tuple[str, str]:
    """The system prompt's ``(static, session)`` parts, built once per session and scope."""
    key = (executor._current_session_id, scope_value)
    frozen = executor._frozen_system.get(key)
    if frozen is not None:
        executor._frozen_system.move_to_end(key)
        return frozen

    static, session = await build_system_blocks(
        base_prompt=executor._load_prompt(),
        context_scope=scope_value,
        harness_block=executor._harness_instruction_block,
        state_repo=executor._state_repo,
        personality=executor._personality,
        profile_name=executor._profile_name,
    )
    try:
        snapshot = (
            await executor._memory_snapshot(executor._current_session_id)
            if executor._memory_snapshot
            else ""
        )
        if snapshot:
            session = session + "\n\n" + snapshot
    except Exception as exc:
        logger.warning("Persistent memory snapshot unavailable: %s", exc)

    executor._frozen_system[key] = (static, session)
    while len(executor._frozen_system) > MAX_FROZEN_SYSTEMS:
        executor._frozen_system.popitem(last=False)
    return static, session


def _record_prefix(executor: ExecutorAgent, system: str, tools: list, prefix_sha: str) -> None:
    """Tell the prefix store what this step will send, so a change is counted (H10)."""
    store = executor._prompt_prefix
    if store is None:
        return
    reason = store.record(executor._current_session_id, system_sha(system), tools_sha(tools))
    if reason is not None:
        logger.info("Prompt prefix changed (%s); now %s", reason, prefix_sha[:12])


def _seed_conversation(
    executor: ExecutorAgent,
    plan: Plan,
    step: Step,
    user_input: str | None,
    preamble: str = "",
) -> None:
    """First turn gets the plan's context; later turns get one line.

    *preamble* (the step context) leads the first message appended, so it is the step's
    first user message and the system prompt stays the same.
    """
    lead = f"{preamble}\n\n---\n\n" if preamble else ""
    if executor._conversation_buffer:
        executor._conversation_buffer.append(
            {"role": "user", "content": f"{lead}Next step: {step.description}"}
        )
        return

    completed_steps = [s for s in plan.steps if s.is_done()]
    try:
        current_idx = plan.steps.index(step) + 1
    except ValueError:
        current_idx = len(completed_steps) + 1

    context_lines = [
        f"Overall goal: {plan.title}",
        f"Total steps: {len(plan.steps)} | Current: step {current_idx}",
    ]
    if plan.message:
        context_lines.append(f"Plan summary: {plan.message}")
    if completed_steps:
        done_summary = "; ".join(s.description for s in completed_steps[-3:])
        context_lines.append(f"Recently completed: {done_summary}")
    context_lines += [
        "",
        f"Current step to execute: {step.description}",
        "",
        "Use available tools to execute this specific step.",
    ]
    executor._conversation_buffer.append(
        {"role": "user", "content": lead + "\n".join(context_lines)}
    )
    # If this is a resume (user provided input), inject it so the LLM sees the answer
    # instead of calling ask_human again.
    if user_input:
        executor._conversation_buffer.append({"role": "user", "content": user_input})


def record_skill_gap(
    executor: ExecutorAgent, step_description: str, best_score: float
) -> None:
    """Record a skill-gap signal when retrieval misses the creation threshold.

    Two output paths:
    1. Append to ``executor._skill_gaps`` for downstream ``IdeaContract``
       creation (existing, processed in ``CompletedState``).
    2. Emit a ``SkillGapDetected`` domain event (new) for lightweight
       subscribers (misalignment journal, diagnostic logger).

    Never raises — both paths are purely additive.
    """
    from weebot.config.feature_flags import SKILL_GAP_TRIGGER_ENABLED
    from weebot.config.learning import TAU_CREATE

    if not SKILL_GAP_TRIGGER_ENABLED:
        return
    if best_score >= TAU_CREATE:
        return  # retrieval hit — no gap

    executor._skill_gaps.append({"step": step_description[:200], "score": best_score})
    logger.debug(
        "Phase 2: skill gap recorded (score=%.3f < %.3f) for step: %s",
        best_score,
        TAU_CREATE,
        step_description[:80],
    )

    # Enhancement 5: emit SkillGapDetected domain event for lightweight subscribers
    try:
        from weebot.domain.models.event import SkillGapDetected

        event = SkillGapDetected(
            session_id=getattr(executor, "_current_session_id", "unknown"),
            step_description=step_description[:200],
            best_score=best_score,
        )
        if executor._event_bus is not None:
            from weebot.core.background_tasks import get_background_tasks

            get_background_tasks().spawn(
                executor._event_bus.publish_domain_event(event), name="skill-gap-detected"
            )
    except Exception:
        logger.debug("SkillGapDetected event emission failed (non-blocking)")
        pass  # event emission must never block the execution loop
