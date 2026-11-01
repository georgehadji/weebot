"""F14 and F13: what the cascade bills, and what it treats as fatal.

F14: `_call_completed` ran only when a reply had content or tool calls, so an empty reply
that carried usage was billed by the provider and never metered, and the model's breaker did
not advance. Usage is now recorded as soon as `chat` returns.

F13: `_is_fast_fail_error` matched `"404"`, `"401"` and `"403"` as bare substrings, so a 429
whose request id held `404` clamped every later timeout to 15 s. It now asks `ErrorClassifier`,
which matches status codes only when they stand alone.
"""

from __future__ import annotations

import unittest.mock as m

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.ports.llm_port import LLMResponse
from weebot.core.error_classifier import ErrorCategory, ErrorClassifier
from weebot.domain.exceptions import AllModelsTrippedError

MODEL = "priced/model"


def _cascade(llm, **kwargs) -> CascadeExecutor:
    tools = m.MagicMock()
    tools.to_params.return_value = []
    return CascadeExecutor(llm=llm, tools=tools, agent_role=None, **kwargs)


class _EmptyWithUsage:
    async def chat(self, **kw):
        usage = {"prompt_tokens": 500, "completion_tokens": 40}
        return LLMResponse(content="", tool_calls=None, usage=usage)


# ── F14 ─────────────────────────────────────────────────────────────────────


async def test_an_empty_reply_that_carries_usage_is_metered():
    seen = []

    async def on_done(event):
        seen.append((event.prompt_tokens, event.completion_tokens))

    ex = _cascade(_EmptyWithUsage(), on_call_completed=on_done)
    result = await ex._cascade_try_chat(
        [{"role": "user", "content": "x"}], MODEL, 5.0
    )
    assert result is None
    assert seen == [(500, 40)]


async def test_an_empty_reply_advances_the_models_breaker():
    ex = _cascade(_EmptyWithUsage())
    await ex._cascade_try_chat([{"role": "user", "content": "x"}], MODEL, 5.0)
    assert ex._circuit_breaker_failures.get(MODEL, 0) == 1


async def test_a_real_reply_is_still_metered_once_and_resets_the_breaker():
    seen = []

    async def on_done(event):
        seen.append(event.prompt_tokens)

    class _Good:
        async def chat(self, **kw):
            return LLMResponse(
                content="ok", tool_calls=None, usage={"prompt_tokens": 7, "completion_tokens": 1}
            )

    ex = _cascade(_Good(), on_call_completed=on_done)
    ex._circuit_breaker_failures[MODEL] = 2
    result = await ex._cascade_try_chat([{"role": "user", "content": "x"}], MODEL, 5.0)
    assert result is not None and seen == [7]
    assert ex._circuit_breaker_failures.get(MODEL, 0) == 0


# ── F13 ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message, fatal",
    [
        ("429 too many requests (request id req_404abc)", False),
        ("Error 429: rate limited, trace 4031-7a", False),
        ("file 1404.txt not found in the cache", False),
        ("Error code: 404 - model not found", True),
        ("No endpoints found for x/y (code: 404)", True),
        ("HTTP 401 Unauthorized", True),
        ("403 Forbidden: key lacks access", True),
        ("invalid api key", True),
        ("permission denied", True),
        ("resource_not_found", True),
        ("request timed out", False),
    ],
)
def test_fast_fail_asks_the_classifier_not_a_substring(message, fatal):
    assert CascadeExecutor._is_fast_fail_error(message) is fatal
    assert CascadeExecutor._is_fast_fail_error(RuntimeError(message)) is fatal


async def test_a_429_with_a_404_in_its_id_does_not_clamp_later_timeouts():
    ex = _cascade(m.MagicMock())
    timeouts_seen: list[bool] = []

    async def fake_try(messages, model, tmo, fast_fail, first_error, **_kw):
        timeouts_seen.append(fast_fail)
        first_error[model] = "429 too many requests (request id req_404abc)"
        return None

    ex._cascade_try_chat = fake_try
    ex._server_error_models.clear()
    with pytest.raises(AllModelsTrippedError):  # nothing answers; the flag passed along matters
        await ex.call_with_cascade([{"role": "user", "content": "x"}], "d")
    assert timeouts_seen and not any(timeouts_seen)


def test_the_live_rescue_is_not_triggered_by_a_substring_either():
    """Same defect, second site: the rescue fires only when every error is a missing model."""
    other = ErrorClassifier.classify(RuntimeError("429 req_404abc"))
    assert other is not ErrorCategory.MODEL_UNAVAILABLE
    assert ErrorClassifier.classify(RuntimeError("code: 404")) is ErrorCategory.MODEL_UNAVAILABLE
