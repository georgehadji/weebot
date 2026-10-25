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

from weebot.application.agents.executor._tool_pairing import sanitize_tool_call_pairing
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

    try:
        response = await executor._cascade.call_with_cascade(
            messages, description=step.description
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
                    message=(
                        "All AI models are currently unavailable. Please:\n"
                        "1. Check your OpenRouter credits at https://openrouter.ai/credits\n"
                        "2. Verify your OPENROUTER_API_KEY is valid\n"
                        "3. Wait a few minutes for circuit breakers to cool down and retry"
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


def _assemble_messages(executor: ExecutorAgent) -> list[dict]:
    """System prompt + tool note + the conversation, repaired for tool-call pairing."""
    messages = sanitize_tool_call_pairing(
        [{"role": "system", "content": executor._system_prompt + executor._tool_note}]
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
