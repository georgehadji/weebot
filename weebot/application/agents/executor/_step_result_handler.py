"""What the executor does with one tool result, apart from showing it to the model.

Extracted from ``ExecutorAgent.execute_step`` (CPL-1 of
``tasks/specs/arch_audit_2026_10_remediation_plan.md``, ADR-007 seams) so the step
loop reads as a loop. Pure decisions and small effects only: the loop still owns
ordering, yielding and the step budget.
"""

from __future__ import annotations

from typing import Any

from weebot.domain.models.event import AgentEvent, ToolApprovalEvent, WaitForUserEvent


def pause_events(result: Any, tool_name: str) -> list[AgentEvent] | None:
    """Events that pause the step for a human, or None when the result asks nothing.

    A tool can ask the person a question (``awaiting_human``), or a guard can ask
    them to approve the call (ADR-013 ``approval_required``). Either way the step
    stops after yielding these.
    """
    data = getattr(result, "data", None) or {}
    if data.get("awaiting_human"):
        return [WaitForUserEvent(question=data.get("question", ""))]
    pending = data.get("approval_required")
    if pending:
        return [
            ToolApprovalEvent(
                tool_name=pending.get("tool_name", tool_name),
                arguments=pending.get("arguments", {}),
                risk_level=pending.get("guard", ""),
                reason=pending.get("reason", ""),
                prompt=pending.get("prompt", "Allow this command? (yes/no)"),
                fingerprint=pending.get("fingerprint", ""),
                allow_always=pending.get("allow_always"),
            ),
            # The UI, CLI and SSE render wait_for_user, not tool_approval: this is
            # the question a person sees.
            WaitForUserEvent(question=pending.get("prompt", "")),
        ]
    return None


async def feed_vision(agent: Any, tool_name: str, result: Any, task_context: str) -> None:
    """Vision-in-the-loop: let a vision-capable model SEE the screen a tool produced.

    Instead of driving blind off DOM/OCR text. Also runs the opt-in observe-then-plan
    reflection, grounded in the step description so the model can judge progress.
    """
    if not getattr(result, "base64_image", None) or not agent._vision_enabled():
        return
    agent._needs_vision = True  # the next LLM call must use a VLM
    compressor = agent._context_compressor
    await compressor.inject_screenshot(tool_name, result.base64_image)
    reflection = await compressor.reflect_on_screenshot(
        tool_name, result.base64_image, task_context=task_context
    )
    if reflection is not None:
        compressor.inject_reflection(reflection)
