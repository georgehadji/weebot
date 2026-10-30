"""F1 (plan 2026-10-29): Telegram ``/new``, ``/reset`` and ``/stop`` act, not just answer.

The commands only returned text: ``/new`` kept the old session, and ``/stop`` was not read
until the run ended, because runs happened inline in the poll loop. ``/new`` and ``/reset``
now close the gateway session, each run is a task per chat so the poll loop keeps reading,
and ``/stop`` cancels that task while ``run_scope`` still tears the tools down.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from weebot.interfaces.gateways import telegram as telegram_mod
from weebot.interfaces.gateways.base import GatewayMessage
from weebot.interfaces.gateways.telegram import TelegramAdapter


class _Resolver:
    """A new flow session id after each close, as GatewayFlowResolver does."""

    def __init__(self) -> None:
        self.generation = 1
        self.closed = 0

    async def resolve(self, key, user_id=None, title=None, metadata=None):
        return None, f"flow-{self.generation}"

    async def close(self, key) -> None:
        self.closed += 1
        self.generation += 1


class _Flow:
    def __init__(self, gate: asyncio.Event | None) -> None:
        self._gate = gate

    async def run(self, text):
        if self._gate is not None:
            await self._gate.wait()

        class _Event:
            type = "message"
            message = f"echo {text}"

        yield _Event()


@pytest.fixture
def adapter(monkeypatch):
    adapter = TelegramAdapter(token="t", state_repo=None, llm=None, flow_resolver=_Resolver())
    adapter.is_authorized = lambda *a, **k: True
    adapter.sent = []
    adapter.scopes = []  # (session id, torn down?)
    adapter.gate = None

    async def _send(response):
        adapter.sent.append(response.text)
        return True

    @asynccontextmanager
    async def _run_scope(session, **kwargs):
        entry = [session.id, False]
        adapter.scopes.append(entry)
        try:
            yield _Flow(adapter.gate)
        finally:
            entry[1] = True

    adapter.send_response = _send
    monkeypatch.setattr(telegram_mod, "run_scope", _run_scope)
    return adapter


def _msg(text: str) -> GatewayMessage:
    return GatewayMessage(platform="telegram", external_id="42", text=text, metadata={})


async def _settle(adapter) -> None:
    for task in list(adapter._runs.values()):
        await asyncio.wait({task})
    await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/new", "/reset"])
async def test_new_then_hi_runs_in_a_fresh_session(adapter, command):
    await adapter._process_message(_msg("hi"))
    await _settle(adapter)
    reply = await adapter._process_message(_msg(command))
    await adapter._process_message(_msg("hi"))
    await _settle(adapter)

    assert adapter._flow_resolver.closed == 1
    assert "reset" in reply.lower()
    assert [s[0] for s in adapter.scopes] == ["flow-1", "flow-2"]


@pytest.mark.asyncio
async def test_the_run_reply_is_sent_when_the_run_ends(adapter):
    assert await adapter._process_message(_msg("hi")) is None
    await _settle(adapter)
    assert adapter.sent == ["echo hi"]


@pytest.mark.asyncio
async def test_stop_cancels_a_run_in_progress_and_tears_it_down(adapter):
    adapter.gate = asyncio.Event()  # never set: the run would wait forever
    await adapter._process_message(_msg("long task"))
    await asyncio.sleep(0)
    assert adapter.scopes == [["flow-1", False]]

    reply = await asyncio.wait_for(adapter._process_message(_msg("/stop")), 1)

    assert "stopped" in reply.lower()
    assert adapter.scopes == [["flow-1", True]]
    assert adapter._runs == {} and adapter.sent == []


@pytest.mark.asyncio
async def test_stop_with_nothing_running_says_so(adapter):
    reply = await adapter._process_message(_msg("/stop"))
    assert "nothing" in reply.lower()


@pytest.mark.asyncio
async def test_a_second_message_during_a_run_does_not_start_another(adapter):
    adapter.gate = asyncio.Event()
    await adapter._process_message(_msg("first"))
    await asyncio.sleep(0)
    reply = await adapter._process_message(_msg("second"))
    assert "/stop" in reply and len(adapter.scopes) == 1
    adapter.gate.set()
    await _settle(adapter)
    assert adapter.sent == ["echo first"]


@pytest.mark.asyncio
async def test_the_poll_loop_keeps_reading_while_a_run_is_in_progress(adapter):
    adapter.gate = asyncio.Event()
    batches = iter([
        [{"update_id": 1, "message": {"text": "long task", "chat": {"id": 42}}}],
        [{"update_id": 2, "message": {"text": "/stop", "chat": {"id": 42}}}],
    ])

    async def _updates():
        await asyncio.sleep(0)  # a real getUpdates waits on the network; the run gets to start
        try:
            return next(batches)
        except StopIteration:
            adapter._running = False
            return []

    adapter._get_updates = _updates
    adapter._running = True
    await asyncio.wait_for(adapter._poll_loop(), 1)

    assert adapter.scopes == [["flow-1", True]]
    assert adapter.sent == ["⏹ Task stopped."]
