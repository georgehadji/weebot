"""R10 (audit 2026-10-29): gateway poll loops back off on errors instead of spinning.

Telegram's ``_get_updates`` returned ``[]`` for an API error (429, 409, 401) just as for
"no messages", so the loop asked again at once, forever: a hot loop that also ignored
Telegram's ``retry_after``. Signal swallowed every receive error the same way. Errors are
now raised, the loops wait with capped exponential backoff, a server's ``retry_after``
wins, and a rejected bot token stops the loop.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.interfaces.gateways import telegram as telegram_mod
from weebot.interfaces.gateways.signal import SignalAdapter
from weebot.interfaces.gateways.telegram import TelegramAdapter, TelegramApiError


def _telegram() -> TelegramAdapter:
    return TelegramAdapter(token="t", state_repo=None, llm=None, flow_resolver=None)


def _record_sleeps(monkeypatch, adapter, stop_after: int) -> list[float]:
    slept: list[float] = []

    async def _sleep(delay):
        slept.append(delay)
        if len(slept) >= stop_after:
            adapter._running = False

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    return slept


def _failing(adapter, attr, errors):
    calls = iter(errors)

    async def _call():
        raise next(calls)

    setattr(adapter, attr, _call)


@pytest.mark.asyncio
async def test_telegram_honours_retry_after(monkeypatch):
    adapter = _telegram()
    adapter._running = True
    _failing(adapter, "_get_updates", [TelegramApiError(429, "slow down", 3)])
    slept = _record_sleeps(monkeypatch, adapter, stop_after=1)
    await adapter._poll_loop()
    assert slept == [3.0]


@pytest.mark.asyncio
async def test_repeated_errors_grow_the_delay_to_the_cap(monkeypatch):
    adapter = _telegram()
    adapter._running = True
    _failing(adapter, "_get_updates", [TelegramApiError(500, "down", None)] * 12)
    slept = _record_sleeps(monkeypatch, adapter, stop_after=12)
    await adapter._poll_loop()
    assert slept[0] <= 1.25 and 45 <= slept[-1] <= 60
    assert max(slept) <= 60


@pytest.mark.asyncio
async def test_a_rejected_token_stops_polling(monkeypatch):
    adapter = _telegram()
    adapter._running = True
    _failing(adapter, "_get_updates", [TelegramApiError(401, "Unauthorized", None)])
    slept = _record_sleeps(monkeypatch, adapter, stop_after=1)
    await adapter._poll_loop()
    assert slept == [] and adapter._running is False


@pytest.mark.asyncio
async def test_get_updates_raises_on_an_api_error(monkeypatch):
    body = {"ok": False, "error_code": 429, "description": "Too Many", "parameters": {"retry_after": 3}}

    class _Resp:
        status = 429

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def json(self, **_):
            return body

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, params):
            return _Resp()

    monkeypatch.setattr(telegram_mod.aiohttp, "ClientSession", _Session)
    with pytest.raises(TelegramApiError) as err:
        await _telegram()._get_updates()
    assert (err.value.code, err.value.retry_after) == (429, 3)


@pytest.mark.asyncio
async def test_signal_backs_off_when_the_service_is_down(monkeypatch):
    adapter = SignalAdapter(state_repo=None, llm=None)
    adapter._running = True
    _failing(adapter, "receive_messages", [ConnectionError("refused")] * 4)
    slept = _record_sleeps(monkeypatch, adapter, stop_after=4)
    await adapter._poll_loop()
    assert len(slept) == 4 and slept[-1] > slept[0]
