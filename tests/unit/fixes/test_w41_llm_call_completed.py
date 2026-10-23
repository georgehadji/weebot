"""W4.1 (F23): every successful executor LLM call is one LLMCallCompleted fact.

Before this, cost lived only in a per-executor ModelCascadeTracker that died
with the executor, and the event store's cost/model/tokens_used columns were
never written. Now the cascade emits LLMCallCompleted on success, the executor
publishes it as a domain event with its session, and DurableEventBus writes
the cost columns, so the store is the one home for cost.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from weebot.application.agents.executor import ExecutorAgent
from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.models.tool_collection import ToolCollection
from weebot.core.model_cascade_config import estimate_cost
from weebot.domain.models.event import LLMCallCompleted
from weebot.domain.models.llm_response import LLMResponse
from weebot.infrastructure.event_bus import AsyncEventBus, DurableEventBus

_USAGE = {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200}


def _response() -> LLMResponse:
    resp = LLMResponse(content="hello")
    resp.usage = dict(_USAGE)
    return resp


async def test_a_successful_call_emits_one_fact_with_model_tokens_and_cost():
    seen: list[LLMCallCompleted] = []

    async def hook(event):
        seen.append(event)

    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_response())
    cascade = CascadeExecutor(llm=llm, tools=MagicMock(), on_call_completed=hook)
    await cascade._cascade_try_chat(
        messages=[{"role": "user", "content": "hi"}], model_id="openai/gpt-4"
    )
    assert len(seen) == 1
    event = seen[0]
    assert event.model == "openai/gpt-4"
    assert (event.prompt_tokens, event.completion_tokens) == (1000, 200)
    assert event.cost == estimate_cost("openai/gpt-4", 1000, 200)


async def test_an_empty_response_emits_nothing():
    seen: list = []

    async def hook(event):
        seen.append(event)

    llm = MagicMock()
    llm.chat = AsyncMock(return_value=LLMResponse(content=""))
    cascade = CascadeExecutor(llm=llm, tools=MagicMock(), on_call_completed=hook)
    await cascade._cascade_try_chat(messages=[], model_id="openai/gpt-4")
    assert seen == []


async def test_a_failing_hook_does_not_fail_the_call():
    async def hook(event):
        raise RuntimeError("store down")

    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_response())
    cascade = CascadeExecutor(llm=llm, tools=MagicMock(), on_call_completed=hook)
    out = await cascade._cascade_try_chat(messages=[], model_id="openai/gpt-4")
    assert out is not None and out.content == "hello"


async def test_the_executor_publishes_it_with_the_step_session():
    bus = MagicMock()
    bus.publish_domain_event = AsyncMock()
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_response())
    executor = ExecutorAgent(llm=llm, tools=ToolCollection(), event_bus=bus)
    executor._current_session_id = "s-42"
    await executor._cascade._cascade_try_chat(messages=[], model_id="openai/gpt-4")
    (event,), _ = bus.publish_domain_event.await_args
    assert isinstance(event, LLMCallCompleted) and event.session_id == "s-42"


async def test_the_durable_bus_writes_the_cost_columns():
    store = MagicMock()
    store.log_event = AsyncMock(return_value=1)
    bus = DurableEventBus(AsyncEventBus(), store)
    event = LLMCallCompleted(
        session_id="s1", model="m", prompt_tokens=10, completion_tokens=5, cost=0.25
    )
    await bus.publish_domain_event(event)
    kwargs = store.log_event.await_args.kwargs
    assert kwargs["session_id"] == "s1" and kwargs["event_type"] == "llm_call_completed"
    assert (kwargs["cost"], kwargs["model"], kwargs["tokens_used"]) == (0.25, "m", 15)
