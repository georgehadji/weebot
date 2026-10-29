"""R03 (audit 2026-10-29): every route records and checks the same principal.

Routers stamped and filtered sessions with the sync ``get_current_user_id``, which in store
mode knows only the legacy key, so a per-principal key came back ``"anonymous"``. The
ownership check resolves through the key store and saw ``"alice"``. So alice's new session
was stamped ``anonymous``, alice got 404 on it, and every store-mode user shared one owner.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from weebot.application.ports.api_key_port import ApiKeyPort, ApiKeyRecord
from weebot.core.api_key_crypto import hash_key, lookup_hash
from weebot.domain.models.session import Session
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository
from weebot.interfaces.web.routers import sessions as router

KEYS = {"wb_alice-key-0123456789": "alice", "wb_bob-key-0123456789ab": "bob"}


class _Keys(ApiKeyPort):
    def __init__(self) -> None:
        self._records = {}
        for raw, principal in KEYS.items():
            key_hash, salt = hash_key(raw)
            self._records[lookup_hash(raw)] = ApiKeyRecord(
                id=principal, principal_id=principal, lookup_hash=lookup_hash(raw),
                key_hash=key_hash, salt=salt,
            )

    async def load_by_lookup_hash(self, lookup: str):
        return self._records.get(lookup)

    async def touch_last_used(self, key_id: str) -> None:
        return None

    async def save(self, *a, **k): ...  # pragma: no cover

    async def load(self, key_id: str): ...  # pragma: no cover

    async def list_by_principal(self, principal_id: str): ...  # pragma: no cover

    async def revoke(self, key_id: str) -> bool: ...  # pragma: no cover


_STORE = _Keys()


def _request(who: str):
    raw = next(k for k, v in KEYS.items() if v == who)
    return SimpleNamespace(
        headers={"X-API-Key": raw}, scope={}, client=SimpleNamespace(host="203.0.113.9"),
        app=SimpleNamespace(state=SimpleNamespace(api_key_store=_STORE)),
        query_params={},
    )


@pytest.fixture(autouse=True)
def _store_mode(monkeypatch):
    monkeypatch.setenv("WEEBOT_AUTH_MODE", "store")
    monkeypatch.setenv("WEEBOT_ENFORCE_SESSION_OWNERSHIP", "true")
    monkeypatch.delenv("WEEBOT_API_KEY", raising=False)


@pytest.mark.asyncio
async def test_a_session_belongs_to_the_principal_who_made_it():
    repo = InMemoryStateRepository()
    body = router.CreateSessionRequest(prompt="hello", session_id="s-alice")
    with patch.object(router, "_respond", AsyncMock()), \
         patch.object(router, "_event_counts", AsyncMock(return_value={})):
        await router.create_session(
            http_request=_request("alice"), body=body, state_repo=repo, _mutation=None
        )
        assert (await repo.load_session("s-alice")).user_id == "alice"

        await router.get_session("s-alice", http_request=_request("alice"), state_repo=repo)
        with pytest.raises(HTTPException) as refused:
            await router.get_session("s-alice", http_request=_request("bob"), state_repo=repo)
        assert refused.value.status_code == 404


@pytest.mark.asyncio
async def test_each_principal_lists_only_their_sessions():
    repo = InMemoryStateRepository()
    await repo.save_session(Session(id="a", user_id="alice"))
    await repo.save_session(Session(id="b", user_id="bob"))
    with patch.object(router, "_event_counts", AsyncMock(return_value={})):
        mine = await router.list_sessions(
            http_request=_request("alice"), status=None, limit=100, offset=0, state_repo=repo
        )
    assert [s.id for s in mine.sessions] == ["a"]


def test_no_router_uses_the_sync_identity_helper():
    """It knows only the legacy key; routers must use current_principal (R03)."""
    import pathlib

    routers = pathlib.Path(router.__file__).parent
    users = [p.name for p in routers.glob("*.py") if "get_current_user_id(" in p.read_text("utf-8")]
    assert users == []
