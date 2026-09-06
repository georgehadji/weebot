"""One place where the factory's timeout and retry budget reaches the SDK client.

Four independent retry/fallback layers sat on top of one another, none aware of
any other, and the product is multiplicative. Measured against a transport that
answers every request with 429 (`tests/unit/adapters/test_retry_amplification.py`):

    CascadeExecutor                    ~5 models   (Phase 1 + Phase 2)
    ResilientLLMAdapter RetryWithBackoff   7 attempts   (len(delays) + 1)
    OpenAIAdapter's own model chain       10 models    (MODEL_FALLBACK_OPENROUTER_CHAIN)
    OpenAI / Anthropic SDK max_retries     3 attempts  (SDK default 2)

One logical ``chat()`` against a rate-limited OpenRouter-shaped model issued
**210** HTTP requests. Against a model with no ``/`` in its name — a one-entry
fallback chain — it issued 42.

The layer that multiplies most is also the one that is architecturally wrong:
``OpenAIAdapter.chat`` catches ``RateLimitError`` and walks a *different*
model chain of its own, beneath the ``CascadeExecutor`` whose entire job is
choosing models (CLAUDE.md design rule 4). So the response the cascade
receives may come from a model the cascade never selected, and the cost is
attributed to the model it *asked* for.

Applied here rather than threaded through ``_create_inner_adapter``'s eight
branches on purpose: a branch that forgets the kwarg is silent, and this file
exists because of a whole class of silent-omission defects. One call site
covers every provider, including the composites, and a fitness test can assert
the factory never returns an adapter without it.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Keep connect fast even when the read budget is long. A scalar `timeout=90.0`
# handed to either SDK replaces the WHOLE Timeout object, widening connect from
# 5s to 90s — so an unreachable host would stall the cascade for 90 seconds
# where it now fails in 5. Verified: `AsyncOpenAI(timeout=90.0).timeout` is
# `90.0`, not `Timeout(connect=5.0, read=90.0, ...)`.
CONNECT_TIMEOUT_S = 5.0

# Child attributes of the composite adapters, walked so that a wrapped or
# paired adapter is configured too.
_CHILD_ATTRS = ("_inner", "_inner_adapter", "_primary", "_secondary")


def build_timeout(seconds: float) -> httpx.Timeout:
    """The factory's per-provider budget as a Timeout that keeps connect fast."""
    return httpx.Timeout(seconds, connect=min(CONNECT_TIMEOUT_S, seconds))


def apply_client_policy(
    adapter: Any,
    *,
    timeout: float | None,
    sdk_max_retries: int = 0,
    model_fallback: bool = False,
) -> int:
    """Push the factory's policy onto every SDK client under *adapter*.

    ``sdk_max_retries=0`` because ``ResilientLLMAdapter`` owns retry. Two retry
    loops do not add, they multiply, and only one of them is configurable by
    the operator.

    ``model_fallback=False`` because ``CascadeExecutor`` owns model choice.

    Returns the number of SDK clients configured, so the caller can tell the
    difference between "policy applied" and "found nothing to apply it to".
    Mutating the constructed client is deliberate and verified: both SDKs read
    ``self.timeout`` and ``self.max_retries`` per request, so a post-hoc change
    reaches the wire (it lands in the request's ``extensions["timeout"]``).
    """
    configured = 0
    for target in _walk(adapter):
        if hasattr(target, "_enable_model_fallback"):
            target._enable_model_fallback = model_fallback

        client = getattr(target, "_client", None)
        if client is None:
            continue
        if hasattr(client, "max_retries"):
            client.max_retries = sdk_max_retries
        if timeout is not None and hasattr(client, "timeout"):
            client.timeout = build_timeout(timeout)
        configured += 1

    if configured == 0:
        logger.debug(
            "No SDK client found under %s; timeout and retry policy not applied.",
            type(adapter).__name__,
        )
    return configured


def _walk(adapter: Any, _seen: set[int] | None = None) -> list[Any]:
    """Every adapter reachable from *adapter*, itself included.

    Composites nest: the factory can return
    ``DirectOrFallbackAdapter(primary=DeepSeekAdapter, secondary=OpenRouterAdapter)``
    wrapped again in ``CachingLLMAdapter``. Configuring only the outermost
    would leave the client that actually makes the call untouched.
    """
    _seen = _seen if _seen is not None else set()
    if adapter is None or id(adapter) in _seen:
        return []
    _seen.add(id(adapter))

    found = [adapter]
    for attr in _CHILD_ATTRS:
        child = getattr(adapter, attr, None)
        if child is not None and not isinstance(child, (str, bytes, int, float, bool)):
            found.extend(_walk(child, _seen))
    return found
