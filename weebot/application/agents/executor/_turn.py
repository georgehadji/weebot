"""One LLM turn inside a step (WB-06, phase 4.2).

The middle of `ExecutorAgent.execute_step` was: assemble the messages, ask the cascade,
handle the two ways a cascade can decline (this process is at its concurrency limit; every
model is circuit-broken), run the response middleware, and emit the thought.

Two things make this worth its own module rather than a helper. The first is that the two
declines are not the same failure and used to give the same advice -- telling a user to
check their credits when the real cause is this process holding all its own LLM slots is
worse than saying nothing. The second is that message assembly is where the session
constraint block and the request middleware have to land in a specific order, and that
order is invisible inside a 400-line loop.

`sanitize_tool_call_pairing` moved to `_tool_pairing.py` with its own docstring; it is
imported here because a turn's messages are the thing it repairs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from weebot.application.agents.executor._loop_detectors import Verdict
from weebot.application.agents.executor._recovery import call_with_recovery
from weebot.application.agents.executor._tool_pairing import sanitize_tool_call_pairing
from weebot.core.error_classifier import ErrorCategory
from weebot.core.log_context import session_id_var
from weebot.core.recovery_ladder import failure_message
from weebot.domain.exceptions import AllModelsTrippedError, LLMCapacityExhaustedError
from weebot.domain.models.event import AgentEvent, ErrorEvent, MessageEvent

if TYPE_CHECKING:
    from weebot.application.agents.executor._base import ExecutorAgent
    from weebot.domain.models.plan import Step

logger = logging.getLogger(__name__)


@dataclass
class TurnOutcome:
    """What one turn produced: events to emit, and whether the step should stop."""

    events: list[AgentEvent] = field(default_factory=list)
    response: Any | None = None
    assistant_content: str = ""
    # The reasoning text, if any. The caller numbers it: the iteration counter belongs to
    # the step's loop, not to one turn.
    thought: str = ""
    stop: bool = False


async def next_turn(executor: ExecutorAgent, step: Step) -> TurnOutcome:
    """Ask the cascade for this turn's response."""
    messages = _assemble_messages(executor)
    messages = await _before_request(executor, messages, step)

    async def rebuild() -> list[dict]:
        return await _before_request(executor, _assemble_messages(executor), step)

    try:
        response, messages = await call_with_recovery(
            executor, messages, step.description, rebuild
        )
    except LLMCapacityExhaustedError as exc:
        # NOT the branch below. That one tells the user to check their credits and API
        # key, which is wrong advice here: nothing is wrong with any provider, this
        # process is simply at its own concurrency limit.
        return TurnOutcome(
            events=[
                ErrorEvent(error=str(exc)),
                MessageEvent(
                    role="assistant",
                    message=(
                        "Weebot is at its limit for simultaneous AI requests, and no "
                        "slot freed up in time. Nothing is wrong with your models or "
                        "credits. Retry shortly, or raise llm_max_concurrent_requests "
                        "if this persists."
                    ),
                ),
            ],
            stop=True,
        )
    except AllModelsTrippedError as exc:
        return TurnOutcome(
            events=[
                ErrorEvent(error=str(exc)),
                MessageEvent(
                    role="assistant",
                    message=failure_message(
                        ErrorCategory(exc.category) if hasattr(exc, "category") else None
                    ),
                ),
            ],
            stop=True,
        )

    content = response.content or ""
    content = await _after_response(executor, content, response, messages)

    assistant_msg: dict = {"role": "assistant", "content": content}
    if response.tool_calls:
        assistant_msg["tool_calls"] = response.tool_calls
    executor._conversation_buffer.append(assistant_msg)

    return TurnOutcome(
        response=response,
        assistant_content=content,
        thought=content.strip(),
    )


def spend_so_far(executor: ExecutorAgent) -> float:
    """What this session has spent, or 0.0 without a cost meter."""
    meter = executor._cost_meter
    return meter.spent(session_id_var.get() or "") if meter is not None else 0.0


def retry_empty_turn(
    executor: ExecutorAgent, guard: Any, turn: TurnOutcome, spent_before: float, step_start: float
) -> bool:
    """True if *turn* was an empty reply that should be asked again (H11).

    The empty assistant message is dropped and a nudge takes its place. Without a cost
    meter the spend is unknown, so the budget is zero and the reply stands.
    """
    if (turn.assistant_content or "").strip():
        return False
    now = spend_so_far(executor)
    verdict = guard.observe_empty_reply(now - spent_before, now - step_start)
    if verdict.kind is not Verdict.RETRY:
        return False
    executor._conversation_buffer.pop()
    executor._conversation_buffer.append({"role": "user", "content": verdict.message})
    return True


def _assemble_messages(executor: ExecutorAgent) -> list[dict]:
    """System prompt + the conversation, repaired for tool-call pairing."""
    messages = sanitize_tool_call_pairing(
        [{"role": "system", "content": executor._system_prompt}]
        + list(executor._conversation_buffer)
    )
    # Lost-in-Compaction: session constraints ride as messages[-1] (the paper's K_ub
    # position, >98% compliance). Appended to the local list, never the buffer, so it
    # cannot be evicted or compacted away.
    if executor._session_constraints_block:
        messages.append({"role": "user", "content": executor._session_constraints_block})
    return messages


async def _before_request(
    executor: ExecutorAgent, messages: list[dict], step: Step
) -> list[dict]:
    chain = executor._middleware_chain
    if chain is None or chain.is_empty():
        return messages
    tools = executor._tools.to_params() if executor._tools else []
    messages, _tools = await chain.apply_before_request(
        messages=messages,
        tools=tools,
        step_id=step.id,
        step_description=step.description,
    )
    return messages


async def _after_response(
    executor: ExecutorAgent, content: str, response: Any, messages: list[dict]
) -> str:
    chain = executor._middleware_chain
    if chain is None or chain.is_empty():
        return content
    content, modified_calls = await chain.apply_after_response(
        content=content,
        tool_calls=response.tool_calls or [],
        messages=messages,
        tools=executor._tools.to_params() if executor._tools else [],
    )
    if response.tool_calls:
        response.tool_calls = modified_calls
    return content
