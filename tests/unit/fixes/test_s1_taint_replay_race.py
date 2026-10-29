"""S1 (remaining-work plan 2026-10-29): the taint replay cannot be skipped or lost.

``claim_hydration`` marked a session replayed before its flags were read, so a second
tool call of the same parallel batch skipped the replay and ran its egress check without
the persisted taint. And ``EffectLedger.flags`` turned an unreadable store into ``[]``, so
one failed read marked the session clean for the rest of the process. A call now waits
for a replay already running, a failed read is retried, and the call that could not read
the store treats the session as tainted.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.unit.test_session_security_state_durable import (
    MemoryStore,
    _executor,
    _restart,
)
from weebot.core.background_tasks import get_background_tasks


class _GatedStore(MemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()
        self.gate.set()
        self.fail_reads = 0
        self.reads = 0

    async def get_session_events(self, session_id, event_type=None):
        self.reads += 1
        await self.gate.wait()
        if self.fail_reads:
            self.fail_reads -= 1
            raise OSError("event store unreachable")
        return await super().get_session_events(session_id, event_type)


@pytest.fixture(autouse=True)
def clean():
    _restart()
    yield
    _restart()


async def _tainted_store() -> _GatedStore:
    store = _GatedStore()
    await _executor(store).execute_tool("web_search", {"query": "x"})
    await get_background_tasks().drain()
    _restart()
    store.reads = 0
    return store


@pytest.mark.asyncio
async def test_a_parallel_call_waits_for_the_replay():
    store = await _tainted_store()
    store.gate.clear()
    first, second = _executor(store), _executor(store)
    one = asyncio.ensure_future(first._hydrate_session_state())
    await asyncio.sleep(0)
    two = asyncio.ensure_future(second._hydrate_session_state())
    for _ in range(3):
        await asyncio.sleep(0)
    assert not two.done(), "the second call must wait for the replay the first one started"
    store.gate.set()
    await asyncio.gather(one, two)
    assert second._untrusted_context_active is True


@pytest.mark.asyncio
async def test_an_unreadable_store_fails_closed_and_is_read_again():
    store = await _tainted_store()
    store.fail_reads = 1
    blind = _executor(store)
    await blind._hydrate_session_state()
    assert blind._untrusted_context_active is True, "an unknown taint must count as tainted"

    later = _executor(store)
    await later._hydrate_session_state()
    assert store.reads == 2, "a failed read must not mark the session replayed"
    assert later._untrusted_context_active is True


@pytest.mark.asyncio
async def test_a_clean_session_is_read_once():
    store = _GatedStore()
    for _ in range(3):
        ex = _executor(store)
        await ex._hydrate_session_state()
        assert ex._untrusted_context_active is False
    assert store.reads == 1
