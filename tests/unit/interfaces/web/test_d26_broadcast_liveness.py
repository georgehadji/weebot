"""D26 — a hung WebSocket client must not stall anybody else.

Two distinct defects share this candidate, and only one of them is a deadlock.

``behavior_router.broadcast_event`` held ``_ws_lock`` across ``await
ws.send_json(...)``.  A client whose socket never drains blocks that await
forever, and because the lock covers the whole loop it is never released.  The
same lock guards connection registration (``behavior_websocket``) and removal
(its ``finally`` block), so the failure closes on itself: the hung client can
never be cleaned up, because cleaning it up needs the lock its own hang is
holding.  New connections wedge too.

``ConnectionManager`` already snapshots under the lock and sends outside it, so
it cannot deadlock -- but its send loop is sequential and has no timeout, so one
hung client still starves every later subscriber of the same session.

Both are proven here by wall-clock: each test bounds the operation it exercises
and fails if the bound is exceeded.  ``asyncio.timeout`` rather than a bare
await, so a regression fails the test instead of hanging the suite.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

from weebot.interfaces.web import websocket as ws_mod
from weebot.interfaces.web.websocket import ConnectionManager

# `from ...routers import behavior_router` yields the APIRouter, not the module:
# routers/__init__.py rebinds the submodule's name to `router`, shadowing it.
br = importlib.import_module("weebot.interfaces.web.routers.behavior_router")

# Every bound below is a multiple of this.  It has to be comfortably larger than
# scheduling jitter and comfortably smaller than the real send timeout.
TICK = 0.05


class HungSocket:
    """A socket whose send never returns until released."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.sent: list[object] = []
        self.cancelled = False

    async def _hang(self, payload: object) -> None:
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        self.sent.append(payload)

    async def send_json(self, payload: object) -> None:
        await self._hang(payload)

    async def send_text(self, payload: object) -> None:
        await self._hang(payload)


class HealthySocket:
    """A socket that accepts anything, immediately."""

    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send_json(self, payload: object) -> None:
        self.sent.append(payload)

    async def send_text(self, payload: object) -> None:
        self.sent.append(payload)


class BrokenSocket:
    """A socket that fails every send, as a dropped client does."""

    async def send_json(self, payload: object) -> None:
        raise ConnectionError("simulated drop")

    async def send_text(self, payload: object) -> None:
        raise ConnectionError("simulated drop")


def _event() -> br.BehaviorEvent:
    return br.BehaviorEvent(
        timestamp="2026-09-05T00:00:00Z",
        event_type="modified",
        path="/tmp/x",
        session_id="s1",
    )


@pytest.fixture
def registry(monkeypatch):
    """Isolate behavior_router's module-level connection registry."""
    monkeypatch.setattr(br, "_ws_connections", [], raising=True)
    monkeypatch.setattr(br, "_ws_lock", asyncio.Lock(), raising=True)
    monkeypatch.setattr(br, "_WS_SEND_TIMEOUT", 4 * TICK, raising=False)
    return br._ws_connections


async def _start_broadcast(hung: HungSocket) -> asyncio.Task:
    """Launch a broadcast and wait until it is genuinely inside the hung send."""
    task = asyncio.create_task(br.broadcast_event(_event()))
    async with asyncio.timeout(20 * TICK):
        await hung.entered.wait()
    return task


# ---------------------------------------------------------------------------
# behavior_router — the deadlock
# ---------------------------------------------------------------------------


async def test_hung_client_does_not_wedge_the_connection_registry(registry):
    """The bug in one line: a stuck send must not hold the registry lock.

    ``behavior_websocket``'s ``finally`` block takes ``_ws_lock`` to remove a
    departing client.  While a broadcast is stuck on a hung socket, that removal
    must still be able to run -- otherwise the only thing that could clear the
    hang is itself blocked by it.
    """
    hung = HungSocket()
    registry.append(hung)

    task = await _start_broadcast(hung)
    try:
        async with asyncio.timeout(20 * TICK):
            async with br._ws_lock:
                pass  # what connect and disconnect both do
    finally:
        hung.release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_hung_client_does_not_block_a_second_broadcast(registry):
    """A stuck client must not make every later event undeliverable."""
    hung = HungSocket()
    healthy = HealthySocket()
    registry.extend([hung, healthy])

    first = await _start_broadcast(hung)
    try:
        async with asyncio.timeout(30 * TICK):
            await br.broadcast_event(_event())
        assert healthy.sent, "second broadcast never reached the healthy client"
    finally:
        hung.release.set()
        await asyncio.gather(first, return_exceptions=True)


async def test_hung_client_does_not_starve_a_healthy_peer(registry):
    """Within a single broadcast, a hung client must not swallow its peers.

    The hung socket is registered first, so a sequential loop reaches it before
    the healthy one and never gets past it.
    """
    hung = HungSocket()
    healthy = HealthySocket()
    registry.extend([hung, healthy])

    try:
        async with asyncio.timeout(30 * TICK):
            await br.broadcast_event(_event())
        assert healthy.sent, "healthy client starved behind a hung peer"
    finally:
        hung.release.set()


async def test_broadcast_gives_up_on_a_client_that_never_returns(registry):
    """The broadcast must terminate on its own, without anyone releasing it."""
    hung = HungSocket()
    registry.append(hung)

    async with asyncio.timeout(40 * TICK):
        await br.broadcast_event(_event())

    assert hung.cancelled, "the timed-out send was left running"


async def test_a_timed_out_client_is_evicted(registry):
    """A client that blew the send timeout is not coming back; drop it.

    Left registered, it would re-impose the timeout on every future broadcast.
    """
    hung = HungSocket()
    healthy = HealthySocket()
    registry.extend([hung, healthy])

    async with asyncio.timeout(40 * TICK):
        await br.broadcast_event(_event())

    assert hung not in br._ws_connections
    assert healthy in br._ws_connections


# ---------------------------------------------------------------------------
# behavior_router — behaviour that must survive the fix
# ---------------------------------------------------------------------------


async def test_broadcast_still_reaches_every_client(registry):
    a, b = HealthySocket(), HealthySocket()
    registry.extend([a, b])

    await br.broadcast_event(_event())

    assert len(a.sent) == 1
    assert len(b.sent) == 1
    assert a.sent[0]["type"] == "file.modified"
    assert a.sent[0]["session_id"] == "s1"


async def test_broken_client_is_still_removed(registry):
    broken, healthy = BrokenSocket(), HealthySocket()
    registry.extend([broken, healthy])

    await br.broadcast_event(_event())

    assert broken not in br._ws_connections
    assert healthy in br._ws_connections
    assert healthy.sent, "a broken peer suppressed delivery to a healthy one"


async def test_empty_registry_is_a_no_op(registry):
    await br.broadcast_event(_event())
    assert br._ws_connections == []


# ---------------------------------------------------------------------------
# ConnectionManager — head-of-line blocking, no deadlock
# ---------------------------------------------------------------------------


@pytest.fixture
def fast_timeout(monkeypatch):
    monkeypatch.setattr(ws_mod, "_WS_SEND_TIMEOUT", 4 * TICK, raising=False)


async def test_session_broadcast_does_not_starve_a_healthy_peer(fast_timeout):
    mgr = ConnectionManager()
    hung, healthy = HungSocket(), HealthySocket()
    mgr._connections["s1"] = {hung, healthy}

    try:
        async with asyncio.timeout(30 * TICK):
            await mgr.broadcast_to_session("s1", {"k": "v"})
        assert healthy.sent, "healthy subscriber starved behind a hung peer"
    finally:
        hung.release.set()


async def test_session_broadcast_terminates_on_a_dead_client(fast_timeout):
    mgr = ConnectionManager()
    hung = HungSocket()
    mgr._connections["s1"] = {hung}

    async with asyncio.timeout(40 * TICK):
        await mgr.broadcast_to_session("s1", {"k": "v"})

    # The empty session key is left behind; only `disconnect` prunes those.
    # Deliberately out of scope here -- D26 is liveness, and an empty set costs
    # one dict entry. Recorded in the audit rather than fixed in passing.
    assert hung not in mgr._connections.get("s1", set()), "timed-out client left registered"


async def test_global_broadcast_does_not_starve_a_healthy_peer(fast_timeout):
    mgr = ConnectionManager()
    hung, healthy = HungSocket(), HealthySocket()
    mgr._global_connections = {hung, healthy}

    try:
        async with asyncio.timeout(30 * TICK):
            await mgr.broadcast_global({"k": "v"})
        assert healthy.sent, "healthy global subscriber starved behind a hung peer"
    finally:
        hung.release.set()


async def test_global_broadcast_evicts_a_timed_out_client(fast_timeout):
    mgr = ConnectionManager()
    hung = HungSocket()
    mgr._global_connections = {hung}

    async with asyncio.timeout(40 * TICK):
        await mgr.broadcast_global({"k": "v"})

    assert hung not in mgr._global_connections


async def test_connection_manager_still_delivers_and_prunes(fast_timeout):
    """The pre-existing contract: everyone gets it, broken clients are dropped."""
    mgr = ConnectionManager()
    broken, healthy = BrokenSocket(), HealthySocket()
    mgr._connections["s1"] = {broken, healthy}

    await mgr.broadcast_to_session("s1", {"k": "v"})

    assert healthy.sent == ['{"k": "v"}']
    assert mgr._connections["s1"] == {healthy}
