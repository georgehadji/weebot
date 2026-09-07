"""D44 — four retry/fallback layers, none aware of the others, multiplying.

D44 was recorded as "No client HTTP timeout on any concrete adapter; the only
timeout is the cascade's own". The second half is false: `ResilientLLMAdapter`
has always wrapped the inner call in `asyncio.wait_for(..., self._timeout)`.
The first half is true of the adapter *code* and misleading about behaviour —
both SDKs supply `Timeout(connect=5.0, read=600, write=600, pool=600)` by
default.

What was actually there is bigger than the claim. Four layers sit on top of one
another and each multiplies the next:

    CascadeExecutor                        ~5 models
    ResilientLLMAdapter RetryWithBackoff    7 attempts   (len(delays) + 1)
    OpenAIAdapter's own model chain        10 models     (MODEL_FALLBACK_OPENROUTER_CHAIN)
    OpenAI SDK max_retries                  3 attempts   (SDK default 2)

Measured against a transport answering 429 to everything, for ONE logical
`chat()`:

    OpenRouter-shaped model ("z-ai/glm-5.2")   210 requests
    plain model ("gpt-4o-mini", 1-entry chain)  42 requests

The third layer is the one that is architecturally wrong as well as the
largest: `OpenAIAdapter.chat` answers a rate limit by walking a *different*
model chain, underneath the `CascadeExecutor` whose entire job is choosing
models. So the response the cascade receives can come from a model it never
selected, and the cost is attributed to the model it asked for.
"""

from __future__ import annotations

import httpx
import pytest

from weebot.infrastructure.adapters.llm._client_policy import apply_client_policy
from weebot.infrastructure.adapters.llm.adapter_factory import AdapterFactory
from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter
from weebot.infrastructure.adapters.llm.resilient_adapter import ResilientLLMAdapter


def _count_requests_through(client) -> dict[str, int]:
    """Swap a counting 429 transport under an SDK client's httpx client.

    `_mounts` is cleared as well as `_transport`, and that is not incidental:
    httpx reads HTTPS_PROXY/NO_PROXY at construction and installs a mounted
    transport per pattern, which is consulted BEFORE `_transport`. Setting only
    `_transport` in a proxied environment leaves the real transport in place —
    the request goes out for real and the test measures nothing. CI has no
    proxy, so the bug would appear only on a developer's machine.
    """
    seen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        # `retry-after-ms` rather than `retry-after`: the SDK only honours
        # `retry-after` for 0 < seconds <= 60, so "0" falls through to its own
        # exponential backoff and ~140 sleeps put the unfixed measurement past
        # the suite's 60s timeout. The REQUEST COUNT is what is measured; the
        # sleeps are not part of the claim.
        return httpx.Response(
            429,
            json={"error": {"message": "rate limited"}},
            headers={"retry-after-ms": "1"},
        )

    hx = client._client
    hx._transport = httpx.MockTransport(handler)
    hx._mounts = {}
    return seen


def _stack(model: str, *, policy: bool) -> tuple[ResilientLLMAdapter, OpenAIAdapter]:
    inner = OpenAIAdapter(api_key="sk-test", default_model=model)
    if policy:
        apply_client_policy(inner, timeout=90.0, sdk_max_retries=0, model_fallback=False)
    res = ResilientLLMAdapter(
        inner_adapter=inner,
        model_name=f"openai/{model}",
        timeout=90.0,
        enable_circuit_breaker=False,
        enable_retry=True,
        enable_caching=False,
    )
    # Zero the backoff sleeps. The REQUEST COUNT is under measurement, not the
    # wall clock; with real delays the unfixed case takes minutes.
    if res._retry is not None:
        res._retry._config.delays = [0] * len(res._retry._config.delays)
    return res, inner


@pytest.mark.timeout(180)
@pytest.mark.asyncio
async def test_one_chat_against_a_rate_limit_is_not_two_hundred_requests():
    """The defect in one number, on the model shape the cascade actually uses.

    Every model the cascade probes is OpenRouter-shaped — it has a `/` — so
    `is_openrouter` is true and the chain is all ten entries. This is the
    common configuration, not a corner.
    """
    unfixed, inner_u = _stack("z-ai/glm-5.2", policy=False)
    seen_u = _count_requests_through(inner_u._client)
    with pytest.raises(Exception):
        await unfixed.chat(messages=[{"role": "user", "content": "hi"}])

    fixed, inner_f = _stack("z-ai/glm-5.2", policy=True)
    seen_f = _count_requests_through(inner_f._client)
    with pytest.raises(Exception):
        await fixed.chat(messages=[{"role": "user", "content": "hi"}])

    assert seen_u["n"] == 210, f"expected the recorded 210, measured {seen_u['n']}"
    assert seen_f["n"] == 7, (
        f"one request per configured retry attempt, measured {seen_f['n']}"
    )


@pytest.mark.asyncio
async def test_the_sdk_no_longer_retries_underneath_the_retry_wrapper():
    """Retry belongs to one layer. Two loops do not add, they multiply.

    Isolated from the model chain by using a model with no `/`, whose chain is
    a single entry: 7 x 2 x 3 = 42 unfixed against 7 x 1 x 1 = 7 fixed.
    """
    unfixed, inner_u = _stack("gpt-4o-mini", policy=False)
    seen_u = _count_requests_through(inner_u._client)
    with pytest.raises(Exception):
        await unfixed.chat(messages=[{"role": "user", "content": "hi"}])

    assert seen_u["n"] == 42, f"expected the recorded 42, measured {seen_u['n']}"
    assert inner_u._client.max_retries == 2, "SDK default assumed by the arithmetic above"

    fixed, inner_f = _stack("gpt-4o-mini", policy=True)
    seen_f = _count_requests_through(inner_f._client)
    with pytest.raises(Exception):
        await fixed.chat(messages=[{"role": "user", "content": "hi"}])

    assert seen_f["n"] == 7
    assert inner_f._client.max_retries == 0


def test_the_factory_pushes_its_timeout_budget_into_the_sdk_client():
    """The factory computed a per-provider timeout and never told the client.

    `timeout` bounded the `asyncio.wait_for` in `ResilientLLMAdapter` and
    nothing else, so the SDK kept its 600s read budget — ten minutes of read
    for a 60s adapter. On any path that does not go through that wrapper, 600s
    was the only bound there was.
    """
    factory = AdapterFactory()
    adapter = factory.create_adapter(provider="openai", model="gpt-4o-mini", api_key="sk-test")
    inner = adapter._inner

    assert adapter._timeout == 60.0, "the provider default this assertion is written against"
    assert inner._client.timeout.read == 60.0, "the adapter's budget did not reach the client"
    assert inner._client.max_retries == 0
    assert inner._enable_model_fallback is False


def test_connect_stays_fast_when_the_read_budget_is_long():
    """A scalar timeout would widen connect from 5s to the read budget.

    REGRESSION GUARD on the fix, not a red-before-green case: connect is 5s on
    the unfixed code too, because that is the SDK default. What this pins is
    that the fix does not trade it away — which the obvious `timeout=90.0`
    spelling would have.

    `AsyncOpenAI(timeout=180.0).timeout` is `180.0` — the scalar replaces the
    whole Timeout object, connect included. An unreachable host would then hang
    a cascade probe for three minutes where it now fails in five seconds. Found
    by checking what the SDK does with a float rather than assuming.
    """
    factory = AdapterFactory()
    # moonshot's provider default is 180s, the longest in the table.
    adapter = factory.create_adapter(provider="openai", model="gpt-4o-mini", api_key="sk-test")
    assert adapter._inner._client.timeout.connect == 5.0

    from weebot.infrastructure.adapters.llm._client_policy import build_timeout

    assert build_timeout(180.0).connect == 5.0
    assert build_timeout(180.0).read == 180.0
    # And a budget shorter than the connect default must not produce a connect
    # timeout longer than the whole request is allowed to take.
    assert build_timeout(2.0).connect == 2.0


def test_the_policy_reaches_a_nested_composite():
    """The factory can return a composite two levels deep.

    `DirectOrFallbackAdapter(primary=DeepSeekAdapter, secondary=OpenRouterAdapter)`,
    wrapped again in `CachingLLMAdapter`. Configuring only the outermost object
    leaves the client that actually makes the call on SDK defaults — and it
    would leave no trace, because the outer object has no `_client` to check.
    """
    from weebot.infrastructure.adapters.llm.caching_llm_adapter import CachingLLMAdapter
    from weebot.infrastructure.adapters.llm.direct_or_fallback_adapter import (
        DirectOrFallbackAdapter,
    )

    primary = OpenAIAdapter(api_key="sk-a", default_model="deepseek/deepseek-v4-flash")
    secondary = OpenAIAdapter(api_key="sk-b", default_model="z-ai/glm-5.2")
    composite = CachingLLMAdapter(
        inner_adapter=DirectOrFallbackAdapter(
            primary=primary,
            secondary=secondary,
            primary_label="deepseek-direct",
            model_prefix="deepseek/",
        ),
        model="deepseek/deepseek-v4-flash",
        enabled=False,
    )

    configured = apply_client_policy(
        composite, timeout=120.0, sdk_max_retries=0, model_fallback=False
    )

    assert configured == 2, f"both leaf clients must be configured, got {configured}"
    for leaf in (primary, secondary):
        assert leaf._client.timeout.read == 120.0
        assert leaf._client.max_retries == 0
        assert leaf._enable_model_fallback is False
