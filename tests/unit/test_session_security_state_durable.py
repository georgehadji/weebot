"""SCL-1 input (plan Phase 8): the executor's taint inputs survive a restart.

Taint, "the tab is local" and "this session wrote that file" decide whether a later
send needs approval, so losing them on a restart changes a security decision. They are
appended to the event store as `session_flag` rows and replayed once per session.
A restart is simulated by clearing the process-level caches.
"""

from __future__ import annotations

import pytest

from tests.unit.test_tool_executor_egress import FakeToolCollection, make_guard
from weebot.application.agents.executor import _tool_executor as te
from weebot.application.agents.executor._tool_executor import ToolExecutor
from weebot.application.services.effect_ledger import EffectLedger
from weebot.core.background_tasks import get_background_tasks

SESSION = "sess-durable-flags"


class MemoryStore:
    """Just the two EventStorePort methods the ledger calls."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def log_event(self, session_id, event_type, data, **_):
        self.rows.append({"session_id": session_id, "event_type": event_type, "data": data})

    async def get_session_events(self, session_id, event_type=None):
        return [
            r for r in self.rows
            if r["session_id"] == session_id and (event_type is None or r["event_type"] == event_type)
        ]


def _executor(store) -> ToolExecutor:
    ex = ToolExecutor(
        tools=FakeToolCollection(), egress_guard=make_guard(), effect_ledger=EffectLedger(store)
    )
    ex.set_step_context("step-1", SESSION, "do it")
    return ex


def _restart() -> None:
    """A new process: the caches are empty and nothing is hydrated."""
    te._TAINTED_SESSIONS.discard(SESSION)
    te._LOCAL_TAB.pop(SESSION, None)
    te._WRITTEN_FILES.pop(SESSION, None)
    te._HYDRATED.discard(SESSION)


@pytest.fixture(autouse=True)
def clean():
    _restart()
    yield
    _restart()


@pytest.mark.asyncio
async def test_taint_survives_a_restart():
    store = MemoryStore()
    await _executor(store).execute_tool("web_search", {"query": "x"})
    await get_background_tasks().drain()
    assert [r["data"]["kind"] for r in store.rows if r["event_type"] == "session_flag"] == ["tainted"]

    _restart()
    after = _executor(store)
    await after.execute_tool("bash", {"command": "echo hi"})  # hydrates; bash itself is LOCAL
    assert after._untrusted_context_active is True


@pytest.mark.asyncio
async def test_taint_is_written_once_per_session():
    store = MemoryStore()
    ex = _executor(store)
    await ex.execute_tool("web_search", {"query": "a"})
    await ex.execute_tool("web_search", {"query": "b"})
    await get_background_tasks().drain()
    assert sum(r["data"]["kind"] == "tainted" for r in store.rows) == 1


@pytest.mark.asyncio
async def test_a_clean_session_stays_clean_after_a_restart():
    store = MemoryStore()
    await _executor(store).execute_tool("bash", {"command": "echo hi"})
    await get_background_tasks().drain()
    _restart()
    after = _executor(store)
    await after.execute_tool("bash", {"command": "echo again"})
    assert after._untrusted_context_active is False


@pytest.mark.asyncio
async def test_a_local_tab_and_written_files_survive_a_restart():
    store = MemoryStore()
    ex = _executor(store)
    await ex.execute_tool("advanced_browser", {"action": "navigate", "url": "file:///C:/o/f.html"})
    await ex.execute_tool("file_editor", {"command": "create", "path": "a.html", "file_text": "x"})
    await get_background_tasks().drain()

    _restart()
    after = _executor(store)
    # Viewing the file this session wrote, and reading the local page, must not taint.
    await after.execute_tool("file_editor", {"command": "view", "path": "a.html"})
    await after.execute_tool("advanced_browser", {"action": "get_text"})
    assert after._untrusted_context_active is False


@pytest.mark.asyncio
async def test_the_taint_row_is_written_before_the_result_is_returned():
    """A crash right after the caller sees the result must not lose the first taint."""
    import asyncio

    class SlowStore(MemoryStore):
        async def log_event(self, *a, **k):
            await asyncio.sleep(0.05)
            await super().log_event(*a, **k)

    store = SlowStore()
    await _executor(store).execute_tool("web_search", {"query": "x"})
    assert [r["data"]["kind"] for r in store.rows] == ["tainted"], "no drain was needed"


@pytest.mark.asyncio
async def test_flags_round_trip_through_the_real_event_store_and_die_with_the_session(tmp_path):
    from weebot.infrastructure.event_store import EventStore

    store = EventStore(db_path=str(tmp_path / "events.db"))
    await _executor(store).execute_tool("web_search", {"query": "x"})
    ledger = EffectLedger(store)
    assert [f["kind"] for f in await ledger.flags(SESSION)] == ["tainted"]

    _restart()
    after = _executor(store)
    await after.execute_tool("bash", {"command": "echo hi"})
    assert after._untrusted_context_active is True

    await store.delete_session(SESSION)
    assert await ledger.flags(SESSION) == [], "flag rows expire with their session"


@pytest.mark.asyncio
async def test_an_unreadable_store_does_not_stop_a_call():
    class Broken(MemoryStore):
        async def get_session_events(self, *a, **k):
            raise RuntimeError("locked")

    result = await _executor(Broken()).execute_tool("bash", {"command": "echo hi"})
    assert not result.is_error
