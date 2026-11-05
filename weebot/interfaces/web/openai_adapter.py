"""Pure translation between Weebot events and OpenAI chat-completion JSON (H12b).

No I/O and no framework imports, so each function is tested on plain values. The router decides
when a run is over (``is_terminal``) and feeds events through ``to_openai_chunk``.
"""

from __future__ import annotations

from typing import Any

from weebot.domain.models.event import (
    DoneEvent,
    ErrorEvent,
    MessageEvent,
    PlanReviewEvent,
    ToolApprovalEvent,
    ToolEvent,
    ToolStatus,
    WaitForUserEvent,
)

MODES = {
    # model id -> execution mode of the run it starts
    "weebot-chat": "interactive",
    "weebot-plan": "interactive",
    "weebot-auto": "auto",
}
PERSONA_PREFIX = "weebot-persona-"

# Events after which a chat completion has nothing more to say: the run ended, or it is waiting
# for a person and the next message of the conversation is the answer.
_TERMINAL = (DoneEvent, WaitForUserEvent, ToolApprovalEvent, PlanReviewEvent)


def is_terminal(event: Any) -> bool:
    return isinstance(event, _TERMINAL)


def model_list(persona_ids: list[str], created: int) -> dict[str, Any]:
    ids = [*MODES, *(PERSONA_PREFIX + p for p in persona_ids)]
    return {
        "object": "list",
        "data": [
            {"id": i, "object": "model", "created": created, "owned_by": "weebot"} for i in ids
        ],
    }


def resolve_model(model: str, persona_ids: list[str]) -> tuple[str, str | None] | None:
    """``(execution_mode, persona_id | None)`` for a model id, or None if it is not ours."""
    if model in MODES:
        return MODES[model], None
    if model.startswith(PERSONA_PREFIX) and model[len(PERSONA_PREFIX) :] in persona_ids:
        return "interactive", model[len(PERSONA_PREFIX) :]
    return None


def event_text(event: Any, show_steps: bool = False) -> str | None:
    """The text an event adds to a reply, or None."""
    if isinstance(event, MessageEvent) and event.role == "assistant":
        return event.message
    if isinstance(event, ErrorEvent):
        return f"[error] {event.error}"
    if isinstance(event, WaitForUserEvent):
        return event.question
    if isinstance(event, ToolApprovalEvent):
        return f"[approval needed] {event.prompt} ({event.tool_name}). Reply yes or no."
    if isinstance(event, PlanReviewEvent):
        return "[plan review] Reply yes to run the plan."
    if show_steps and isinstance(event, ToolEvent) and event.status == ToolStatus.CALLING:
        return f"[tool] {event.function_name or event.tool_name}"
    return None


def _chunk(cid: str, model: str, created: int, delta: dict, finish: str | None) -> dict[str, Any]:
    return {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def to_openai_chunk(
    event: Any, *, completion_id: str, model: str, created: int, show_steps: bool = False
) -> dict[str, Any] | None:
    """One ``chat.completion.chunk`` for *event*, or None when it adds nothing."""
    text = event_text(event, show_steps)
    finish = "stop" if is_terminal(event) else None
    if text is None and finish is None:
        return None
    delta = {"content": text + "\n"} if text else {}
    return _chunk(completion_id, model, created, delta, finish)


def role_chunk(completion_id: str, model: str, created: int) -> dict[str, Any]:
    return _chunk(completion_id, model, created, {"role": "assistant", "content": ""}, None)


def completion_body(
    *, completion_id: str, model: str, created: int, content: str, usage: dict, extra: dict
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
        "x_weebot": extra,
    }


def message_text(content: Any) -> str:
    """The text of an OpenAI message ``content``: a string, or a list of ``text`` parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p for p in content if isinstance(p, dict) and p.get("type") == "text"]
        return "\n".join(str(p.get("text", "")) for p in parts)
    return ""
