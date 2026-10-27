"""A26 repros (strict xfail until each part is fixed): LLM accounting gaps.

Each test is one gap named in the audit: cached prompt tokens priced at the full rate,
cancelled hedge probes billed but unrecorded, timeouts that never trip the cascade breaker,
timeouts retried many times with no deadline, an image call that buys again after a paid 200,
and a hard cost limit checked only between steps."""

from __future__ import annotations

import asyncio
import contextlib
import unittest.mock as m

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.ports.llm_port import LLMResponse
from weebot.core.model_cascade_config import estimate_cost

PRICED = "deepseek/deepseek-chat"


# ── cached prompt tokens ────────────────────────────────────────────────────


def test_cached_prompt_tokens_cost_less():
    full = estimate_cost(PRICED, 1_000_000, 0)
    cached = estimate_cost(PRICED, 1_000_000, 0, cached_prompt=900_000)
    assert 0 < cached < full
    assert cached == pytest.approx(full * 0.19)  # 10% of the prompt uncached, 90% at a tenth


def test_cached_tokens_never_exceed_the_prompt_or_go_negative():
    full = estimate_cost(PRICED, 1000, 0)
    assert estimate_cost(PRICED, 1000, 0, cached_prompt=10**9) == pytest.approx(full * 0.1)
    assert estimate_cost(PRICED, 1000, 0, cached_prompt=-5) == pytest.approx(full)


async def test_a_completed_call_reports_its_cached_tokens_at_the_cache_rate(monkeypatch):
    seen = []

    async def on_done(event):
        seen.append(event.cost)

    class _Cached:
        async def chat(self, **kw):
            if kw.get("model") != PRICED:
                raise RuntimeError("only the priced model answers")
            usage = {"prompt_tokens": 1000, "completion_tokens": 0, "cached_tokens": 1000}
            return LLMResponse(content="ok", tool_calls=None, usage=usage)

    ex = _cascade(_Cached(), [PRICED], monkeypatch, on_call_completed=on_done)
    await ex.call_with_cascade(messages=[{"role": "user", "content": "x"}], description="d")
    assert seen == [pytest.approx(estimate_cost(PRICED, 1000, 0) * 0.1)]


# ── cascade harness (the one used by test_cascade_does_not_bill_orphans) ────


async def _ident(models, *a, **k):
    return models


def _cascade(llm, probes, monkeypatch, **kwargs) -> CascadeExecutor:
    import weebot.config.model_refs as refs

    monkeypatch.setattr(refs, "get_model_cascade_for_role", lambda role: ["dead/never"])
    for tier in ("_TIER2_MODEL", "_TIER3_MODEL", "_TIER4_MODEL"):
        monkeypatch.setattr(CascadeExecutor, tier, "dead/never", raising=False)
    monkeypatch.setattr(CascadeExecutor, "get_credits_and_filter_direct", staticmethod(_ident))
    tools = m.MagicMock()
    tools.to_params.return_value = []
    return CascadeExecutor(
        llm=llm, tools=tools, agent_role=None, model_provider=lambda d: list(probes),
        on_success=None, **kwargs,
    )


class _Llm:
    def __init__(self, behaviour):
        self._behaviour = behaviour  # model -> (delay, "ok" | "fail" | "timeout")

    async def chat(self, **kwargs):
        model = kwargs.get("model")
        delay, how = self._behaviour.get(model, (5.0, "fail"))
        await asyncio.sleep(delay)
        if how == "timeout":
            raise TimeoutError
        if how == "fail":
            raise RuntimeError("injected")
        return LLMResponse(content=f"ok {model}", tool_calls=None, usage=None)


@pytest.mark.xfail(strict=True, reason="A26: a cancelled hedge probe is billed but not recorded")
async def test_a_cancelled_probe_is_recorded_as_spend(monkeypatch):
    seen = []

    async def on_done(event):
        seen.append(event.model)

    llm = _Llm({"fast/ok": (0.01, "ok"), "slow/probe": (3.0, "ok")})
    ex = _cascade(llm, ["fast/ok", "slow/probe"], monkeypatch, on_call_completed=on_done)
    ex._HEDGE_DELAY_S = 0.0  # start the second probe at once
    await ex.call_with_cascade(messages=[{"role": "user", "content": "x"}], description="d")
    assert "slow/probe" in seen


@pytest.mark.xfail(strict=True, reason="A26: a timeout never trips the cascade breaker")
async def test_a_timeout_counts_toward_the_breaker(monkeypatch):
    llm = _Llm({"slow/timeout": (0.0, "timeout")})
    ex = _cascade(llm, ["slow/timeout"], monkeypatch)
    with contextlib.suppress(Exception):  # nothing answers; only the breaker count matters
        await ex.call_with_cascade(messages=[{"role": "user", "content": "x"}], description="d")
    assert ex._circuit_breaker_failures.get("slow/timeout", 0) >= 1


# ── retry policy ────────────────────────────────────────────────────────────


@pytest.mark.xfail(strict=True, reason="A26: a timeout is retried as if it were transient")
async def test_a_timeout_is_retried_at_most_once(monkeypatch):
    from weebot.infrastructure.adapters.llm.resilient_adapter import ResilientLLMAdapter

    calls = []

    class _Inner:
        async def chat(self, **kw):
            calls.append(1)
            raise TimeoutError

    async def no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    adapter = ResilientLLMAdapter(_Inner(), "x/model", timeout=1.0, enable_circuit_breaker=False)
    with pytest.raises(Exception):
        await adapter.chat(messages=[{"role": "user", "content": "x"}])
    assert len(calls) <= 2


# ── media: a paid 200 is not bought again ───────────────────────────────────


@pytest.mark.xfail(strict=True, reason="A26: an image call buys again after a paid 200")
async def test_an_unusable_paid_200_stops_the_image_cascade(monkeypatch, tmp_path):
    import aiohttp

    from weebot.tools.image_gen_tool import ImageGenParams, ImageGenTool

    posts = []

    class _Resp:
        status = 200

        async def json(self):
            return {"choices": [{"message": {"content": "no image here"}}]}

        async def text(self):
            return ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, *a, **k):
            posts.append(1)
            return _Resp()

    monkeypatch.setattr(aiohttp, "ClientSession", lambda *a, **k: _Session())
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-for-a26")  # test value, never sent anywhere
    params = ImageGenParams(prompt="a cat", output_path=str(tmp_path / "cat.png"))
    await ImageGenTool()._execute_openrouter(params)
    assert len(posts) == 1


# ── hard limit inside a step ────────────────────────────────────────────────


@pytest.mark.xfail(strict=True, reason="A26: the hard limit is checked only between steps")
async def test_the_hard_limit_stops_the_next_call_inside_a_step(monkeypatch):
    from weebot.application.services.session_cost import SessionCostMeter
    from weebot.core.log_context import log_context

    meter = SessionCostMeter(hard_usd=1.0)
    meter.add("s1", 5.0)  # already past the limit
    called = []

    class _CountingLlm:
        async def chat(self, **kw):
            called.append(1)
            return LLMResponse(content="ok", tool_calls=None, usage=None)

    ex = _cascade(_CountingLlm(), ["a/b"], monkeypatch, cost_meter=meter)
    with log_context(session_id="s1"):
        with pytest.raises(Exception):
            await ex.call_with_cascade(messages=[{"role": "user", "content": "x"}], description="d")
    assert called == []
