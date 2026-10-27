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

from weebot.application.agents.executor._prompt_builder import build_executor_prompt

if TYPE_CHECKING:
    from weebot.application.agents.executor._base import ExecutorAgent
    from weebot.domain.models.plan import Plan, Step

logger = logging.getLogger(__name__)


@dataclass
class StepPrime:
    """What the caller needs after the step's context is bound."""

    tool_note: str
    span: Any | None


def prime_step(executor: ExecutorAgent, step: Step, session_id: str) -> StepPrime:
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
    tool_note = executor._scope_tools_for(step)
    return StepPrime(tool_note=tool_note, span=span)


async def build_step_prompts(
    executor: ExecutorAgent, plan: Plan, step: Step, user_input: str | None
) -> None:
    """Assemble the system prompt and seed the conversation buffer for this step."""
    executor._tool_note = executor._scope_tools_for(step)
    await _load_user_profile(executor)

    step_scope = getattr(step, "context_scope", None)
    scope_value = step_scope.value if step_scope is not None else "full"
    system_prompt = await build_executor_prompt(
        step_description=step.description,
        base_prompt=executor._load_prompt(),
        context_scope=scope_value,
        harness_block=executor._harness_instruction_block,
        skill_prompt=executor._skill_prompt,
        skill_retriever=executor._skill_retriever,
        behavioral_learner=executor._behavioral_learner,
        state_repo=executor._state_repo,
        personality=executor._personality,
        profile_name=executor._profile_name,
        skills_used=executor._skills_used,
    )

    # Gated by scope: minimal/skill steps don't need the cached user profile blob
    # (ICM per-step context scoping — see _prompt_builder).
    if scope_value in ("full", "creative") and getattr(executor, "_user_profile_cache", ""):
        system_prompt += f"\n\n## User Profile\n{executor._user_profile_cache}"

    executor._system_prompt = system_prompt
    # Inject OUTPUT_ROOT so tools resolve paths consistently
    from weebot.core.output_path import output_path as _op

    executor._system_prompt = executor._system_prompt + (
        f"\n\nOUTPUT_ROOT = {_op('Output')}"
        "\nALL file writes MUST use this absolute path prefix. "
        'Example: Set-Content -Path "{OUTPUT_ROOT}/refactor/file.md" -Value ...'
    )

    try:
        snapshot = await executor._memory_snapshot() if executor._memory_snapshot else ""
        if snapshot:
            executor._system_prompt = executor._system_prompt + "\n\n" + snapshot
    except Exception as exc:
        logger.warning("Persistent memory snapshot unavailable: %s", exc)

    _seed_conversation(executor, plan, step, user_input)


async def _load_user_profile(executor: ExecutorAgent) -> None:
    """Lazily fetch the dialectic-consolidation profile once per executor.

    A failure here is not the step's problem: an empty profile costs a paragraph of
    prompt, and refusing to run costs the task.
    """
    if hasattr(executor, "_user_profile_cache"):
        return

    try:
        import hashlib

        from weebot.application.ports.state_roles_port import MemoryMetadataStore, as_role

        repo = as_role(executor._state_repo, MemoryMetadataStore)
        if repo is None:
            executor._user_profile_cache = ""
            return
        key = hashlib.sha256(b"user_model_profile").hexdigest()[:16]
        row = await repo.get_memory_entry(key)
        text = row.get("entry_text", "") if row else ""
        executor._user_profile_cache = (
            text[:500] if text and text != "No user data collected yet." else ""
        )
    except Exception:
        executor._user_profile_cache = ""


def _seed_conversation(
    executor: ExecutorAgent, plan: Plan, step: Step, user_input: str | None
) -> None:
    """First turn gets the plan's context; later turns get one line."""
    if executor._conversation_buffer:
        executor._conversation_buffer.append(
            {"role": "user", "content": f"Next step: {step.description}"}
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
    executor._conversation_buffer.append({"role": "user", "content": "\n".join(context_lines)})
    # If this is a resume (user provided input), inject it so the LLM sees the answer
    # instead of calling ask_human again.
    if user_input:
        executor._conversation_buffer.append({"role": "user", "content": user_input})
