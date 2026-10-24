"""Web auth resolves API keys through ApiKeyPort, with no infrastructure import.

Plan item 1.2 (SEC-2) of tasks/specs/arch_audit_2026_10_remediation_plan.md. The
fake port keeps SQLite out of it: what is under test is the resolution rule.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from weebot.application.ports.api_key_port import ApiKeyPort, ApiKeyRecord
from weebot.core.api_key_crypto import hash_key, lookup_hash
from weebot.interfaces.web import auth

RAW = "wb_unit-test-key-0123456789"


class FakeKeys(ApiKeyPort):
    def __init__(self, *, revoked=False, expires_at=None, touch_raises=False) -> None:
        key_hash, salt = hash_key(RAW)
        self.record = ApiKeyRecord(
            id="k1",
            principal_id="alice",
            lookup_hash=lookup_hash(RAW),
            key_hash=key_hash,
            salt=salt,
            expires_at=expires_at,
            revoked_at=datetime.now(UTC) if revoked else None,
        )
        self.touched: list[str] = []
        self._touch_raises = touch_raises

    async def save(self, *a, **k) -> None:  # pragma: no cover - unused
        raise NotImplementedError

    async def load_by_lookup_hash(self, lookup: str):
        return self.record if lookup == self.record.lookup_hash else None

    async def load(self, key_id: str):  # pragma: no cover - unused
        return self.record

    async def list_by_principal(self, principal_id: str):  # pragma: no cover - unused
        return [self.record]

    async def revoke(self, key_id: str) -> bool:  # pragma: no cover - unused
        return True

    async def touch_last_used(self, key_id: str) -> None:
        if self._touch_raises:
            raise RuntimeError("db is locked")
        self.touched.append(key_id)


def _request(keys=None, api_key: str = RAW):
    return SimpleNamespace(
        headers={"X-API-Key": api_key},
        app=SimpleNamespace(state=SimpleNamespace(api_key_store=keys)),
        client=SimpleNamespace(host="203.0.113.9"),
    )


class TestPrincipalFromKey:
    @pytest.mark.asyncio
    async def test_a_valid_key_resolves_and_is_touched(self):
        keys = FakeKeys()
        assert await auth._principal_from_key(RAW, keys) == "alice"
        assert keys.touched == ["k1"]

    @pytest.mark.asyncio
    async def test_an_unknown_key_resolves_to_none(self):
        assert await auth._principal_from_key("wb_other", FakeKeys()) is None

    @pytest.mark.asyncio
    async def test_a_revoked_key_resolves_to_none(self):
        assert await auth._principal_from_key(RAW, FakeKeys(revoked=True)) is None

    @pytest.mark.asyncio
    async def test_an_expired_key_resolves_to_none(self):
        keys = FakeKeys(expires_at=datetime.now(UTC) - timedelta(days=1))
        assert await auth._principal_from_key(RAW, keys) is None

    @pytest.mark.asyncio
    async def test_a_record_whose_hash_does_not_match_never_verifies(self):
        keys = FakeKeys()
        keys.record.key_hash = "0" * 64
        assert await auth._principal_from_key(RAW, keys) is None

    @pytest.mark.asyncio
    async def test_a_failed_timestamp_does_not_turn_a_valid_key_away(self, caplog):
        keys = FakeKeys(touch_raises=True)
        assert await auth._principal_from_key(RAW, keys) == "alice"
        assert "could not record last use" in caplog.text


class TestResolveUser:
    @pytest.mark.asyncio
    async def test_store_mode_uses_the_port_on_app_state(self, monkeypatch):
        monkeypatch.setenv("WEEBOT_AUTH_MODE", "store")
        assert await auth._resolve_user(_request(FakeKeys())) == "alice"

    @pytest.mark.asyncio
    async def test_store_mode_with_no_store_wired_does_not_authenticate(self, monkeypatch):
        monkeypatch.setenv("WEEBOT_AUTH_MODE", "store")
        monkeypatch.delenv("WEEBOT_API_KEY", raising=False)
        assert await auth._resolve_user(_request(None)) == "anonymous"

    @pytest.mark.asyncio
    async def test_store_mode_wrong_key_is_anonymous(self, monkeypatch):
        monkeypatch.setenv("WEEBOT_AUTH_MODE", "store")
        monkeypatch.delenv("WEEBOT_API_KEY", raising=False)
        assert await auth._resolve_user(_request(FakeKeys(), api_key="wb_nope")) == "anonymous"

    @pytest.mark.asyncio
    async def test_the_async_dependency_prefers_an_explicit_port(self, monkeypatch):
        monkeypatch.setenv("WEEBOT_AUTH_MODE", "store")
        user = await auth.get_current_user_id_async(_request(None), api_key_port=FakeKeys())
        assert user == "alice"


def test_auth_imports_nothing_from_infrastructure():
    """The point of SEC-2: the interface layer does not reach into an adapter."""
    source = pathlib.Path(auth.__file__).read_text(encoding="utf-8")
    imported = [
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not [m for m in imported if m.startswith("weebot.infrastructure")], imported
