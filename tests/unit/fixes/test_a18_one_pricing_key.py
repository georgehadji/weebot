"""A18: a direct provider answers with its bare model id ("deepseek-chat"), which the
price catalog does not list ("deepseek/deepseek-chat"), so the call cost 0.0."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from weebot.application.ports.llm_port import LLMResponse
from weebot.application.strategies.llm_pool import BoundedLLMAdapter, LLMPool
from weebot.core.model_cascade_config import estimate_cost
from weebot.infrastructure.adapters.llm.direct_or_fallback_adapter import (
    DirectOrFallbackAdapter,
)

PRICED = "deepseek/deepseek-chat"
USAGE = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}


class _Direct:
    """A direct adapter: answers with the bare id, never the catalog id."""

    def __init__(self) -> None:
        self._client = SimpleNamespace(api_key="sk-test")

    async def chat(self, **_kw):
        return LLMResponse(content="ok", model="deepseek-chat", usage=dict(USAGE))


class _Fallback(_Direct):
    async def chat(self, **kw):
        return LLMResponse(content="ok", model=kw.get("model") or "", usage=dict(USAGE))


def test_the_catalog_prices_the_prefixed_id():
    assert estimate_cost(PRICED, 1_000_000, 1_000_000) > 0


async def test_the_direct_adapter_stamps_the_requested_id_on_its_answer():
    adapter = DirectOrFallbackAdapter(_Direct(), _Fallback(), primary_label="t")
    response = await adapter.chat(messages=[{"role": "user", "content": "x"}], model=PRICED)
    assert response.model == PRICED


async def test_a_direct_call_is_priced_above_zero():
    published = []

    async def publish(event):
        published.append(event)

    adapter = DirectOrFallbackAdapter(_Direct(), _Fallback(), primary_label="t")
    bounded = BoundedLLMAdapter(adapter, LLMPool(max_concurrent=1), on_completed=publish)
    await bounded.chat(messages=[{"role": "user", "content": "x"}], model=PRICED)
    [event] = published
    assert event.cost > 0


async def test_the_requested_catalog_id_wins_over_a_bare_answer():
    published = []

    async def publish(event):
        published.append(event)

    bounded = BoundedLLMAdapter(_Direct(), LLMPool(max_concurrent=1), on_completed=publish)
    await bounded.chat(messages=[{"role": "user", "content": "x"}], model=PRICED)
    assert published[0].cost == estimate_cost(PRICED, 1_000_000, 1_000_000) > 0


def test_a_catalog_miss_is_a_warning_once_per_id(caplog):
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert estimate_cost("no-such/model-a18", 10, 10) == 0.0
    misses = [r for r in caplog.records if "no-such/model-a18" in r.getMessage()]
    assert len(misses) == 1 and misses[0].levelno == logging.WARNING
