"""R11 (audit 2026-10-29): every OpenAIAdapter subclass sets up what the base reads.

OpenRouterAdapter built its own client and never called the parent constructor, so
``_enable_model_fallback`` did not exist. The client policy sets it only ``if hasattr``,
so under the factory it stayed missing too, and every 429 from OpenRouter surfaced as
``AttributeError`` instead of a rate-limit error the cascade knows how to skip past.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from openai import RateLimitError

from weebot.infrastructure.adapters.llm._client_policy import apply_client_policy
from weebot.infrastructure.adapters.llm.deepseek_adapter import DeepSeekAdapter
from weebot.infrastructure.adapters.llm.moonshot_adapter import MoonshotAdapter
from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter
from weebot.infrastructure.adapters.llm.openrouter_adapter import OpenRouterAdapter

SUBCLASSES = [OpenRouterAdapter, DeepSeekAdapter, MoonshotAdapter]


def _rate_limited() -> RateLimitError:
    request = httpx.Request("POST", "https://example.invalid/chat/completions")
    return RateLimitError(
        "rate limited", response=httpx.Response(429, request=request), body=None
    )


@pytest.mark.parametrize("cls", SUBCLASSES, ids=lambda c: c.__name__)
def test_the_base_attributes_exist(cls):
    adapter = cls(api_key="test-key-not-real")
    for name in ("_client", "_default_model", "_enable_model_fallback"):
        assert hasattr(adapter, name), f"{cls.__name__} lacks {name}"


def test_the_openrouter_client_keeps_its_headers():
    adapter = OpenRouterAdapter(api_key="sk-or-v1-test", x_title="t")
    assert adapter._client.default_headers["X-Title"] == "t"
    assert str(adapter._client.base_url).startswith("https://openrouter.ai")


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [OpenAIAdapter, *SUBCLASSES], ids=lambda c: c.__name__)
async def test_a_429_under_the_factory_policy_stays_a_rate_limit_error(cls):
    adapter = cls(api_key="test-key-not-real")
    apply_client_policy(adapter, timeout=None, model_fallback=False)
    adapter._client.chat.completions.create = AsyncMock(side_effect=_rate_limited())
    with pytest.raises(RateLimitError):
        await adapter.chat([{"role": "user", "content": "hi"}], model="some/model")
    assert adapter._client.chat.completions.create.await_count == 1  # no own fallback chain
