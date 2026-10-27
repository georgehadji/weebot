"""Contract for gateway session stores (audit A02).

Every store must survive a second read: `SQLiteGatewaySessionStore._row_to_session`
once called `.get` on a `sqlite3.Row`, so any lookup after the first message failed.
Add each new `AbstractGatewaySessionStore` implementation to `STORES`.
"""

from __future__ import annotations

import pytest

from weebot.domain.models.gateway_session import GatewaySession, GatewaySessionKey
from weebot.infrastructure.persistence.gateway_session_store import SQLiteGatewaySessionStore


def _sqlite(tmp_path):
    return SQLiteGatewaySessionStore(tmp_path / "gw.db")


STORES = [pytest.param(_sqlite, id="sqlite")]


@pytest.fixture(params=STORES)
def store(request, tmp_path):
    return request.param(tmp_path)


def _session(chat_id="1", thread_id=None, title=None, user_id=None) -> GatewaySession:
    key = GatewaySessionKey(platform="telegram", chat_id=chat_id, thread_id=thread_id)
    return GatewaySession(
        key=key, flow_session_id=f"flow-{chat_id}", title=title, user_id=user_id
    )


async def test_get_returns_what_upsert_stored(store):
    await store.upsert(_session("1", title="hello", user_id="u1"))
    got = await store.get(_session("1").key)
    assert got is not None
    assert (got.flow_session_id, got.title, got.user_id) == ("flow-1", "hello", "u1")


async def test_get_keeps_the_thread_id(store):
    await store.upsert(_session("1", thread_id="t9"))
    got = await store.get(_session("1", thread_id="t9").key)
    assert got is not None and got.key.thread_id == "t9"


async def test_get_of_a_missing_key_is_none(store):
    assert await store.get(_session("nope").key) is None


async def test_list_reads_every_row(store):
    await store.upsert(_session("1", user_id="u1"))
    await store.upsert(_session("2", user_id="u2"))
    assert {s.key.chat_id for s in await store.list()} == {"1", "2"}
    assert [s.key.chat_id for s in await store.list(user_id="u2")] == ["2"]


async def test_upsert_twice_replaces(store):
    await store.upsert(_session("1", title="a"))
    await store.upsert(_session("1", title="b"))
    assert [s.title for s in await store.list()] == ["b"]


async def test_close_hides_from_the_active_list(store):
    await store.upsert(_session("1"))
    await store.close_session(_session("1").key)
    assert await store.list() == []
    assert len(await store.list(active_only=False)) == 1
