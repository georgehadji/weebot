"""Unit tests for the API key store (SQLiteApiKeyStore).

Tests cover key lifecycle: create, hash, validate, revoke, expiry.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC

import pytest

from weebot.infrastructure.security.sqlite_api_key_store import (
    SQLiteApiKeyStore,
    _lookup_hash,
    _hash_key,
    _verify_key,
)


@pytest.fixture
async def store():
    s = SQLiteApiKeyStore(db_path=":memory:")
    yield s
    await s.close()


class TestKeyHashing:
    """Verify deterministic lookup and scrypt hash functions."""

    def test_lookup_hash_is_deterministic(self):
        assert _lookup_hash("hello") == _lookup_hash("hello")
        assert _lookup_hash("hello") != _lookup_hash("world")

    def test_scrypt_round_trip(self):
        key_hash, salt = _hash_key("test-key")
        assert _verify_key("test-key", key_hash, salt)
        assert not _verify_key("wrong-key", key_hash, salt)

    def test_scrypt_different_salts(self):
        h1, s1 = _hash_key("same-key")
        h2, s2 = _hash_key("same-key")
        assert h1 != h2  # Different salts → different scrypt hashes
        assert s1 != s2

    def test_lookup_and_verify_together(self):
        """Full flow: lookup hash finds record, scrypt+salt verifies it."""
        raw = SQLiteApiKeyStore.generate_raw_key()
        lookup = _lookup_hash(raw)
        key_hash, salt = _hash_key(raw)

        assert lookup == _lookup_hash(raw)  # deterministic
        assert _verify_key(raw, key_hash, salt)  # correct key
        assert not _verify_key("impostor", key_hash, salt)  # wrong key

    def test_key_generation(self):
        raw = SQLiteApiKeyStore.generate_raw_key()
        assert raw.startswith("wb_")
        assert len(raw) > 64


class TestKeyLifecycle:
    """Full lifecycle through the store adapter."""

    @pytest.mark.asyncio
    async def test_save_and_load_by_lookup(self, store: SQLiteApiKeyStore):
        raw = SQLiteApiKeyStore.generate_raw_key()
        lookup = _lookup_hash(raw)
        key_hash, salt = _hash_key(raw)

        await store.save("k1", "user-1", lookup, key_hash, salt, ["api"])
        record = await store.load_by_lookup_hash(lookup)
        assert record is not None
        assert record.principal_id == "user-1"
        assert "api" in record.scopes
        assert record.is_valid
        assert _verify_key(raw, record.key_hash, record.salt)

    @pytest.mark.asyncio
    async def test_load_by_lookup_missing(self, store: SQLiteApiKeyStore):
        record = await store.load_by_lookup_hash("deadbeef")
        assert record is None

    @pytest.mark.asyncio
    async def test_load_by_id(self, store: SQLiteApiKeyStore):
        raw = SQLiteApiKeyStore.generate_raw_key()
        lookup = _lookup_hash(raw)
        key_hash, salt = _hash_key(raw)

        await store.save("k-by-id", "user-x", lookup, key_hash, salt)
        record = await store.load("k-by-id")
        assert record is not None
        assert record.principal_id == "user-x"

    @pytest.mark.asyncio
    async def test_list_by_principal(self, store: SQLiteApiKeyStore):
        r1, r2 = SQLiteApiKeyStore.generate_raw_key(), SQLiteApiKeyStore.generate_raw_key()
        h1, s1 = _hash_key(r1)
        h2, s2 = _hash_key(r2)
        await store.save("k1", "user-a", _lookup_hash(r1), h1, s1)
        await store.save("k2", "user-a", _lookup_hash(r2), h2, s2)
        await store.save("k3", "user-b", _lookup_hash(r2), h2, s2)
        records = await store.list_by_principal("user-a")
        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_revoke(self, store: SQLiteApiKeyStore):
        raw = SQLiteApiKeyStore.generate_raw_key()
        lookup = _lookup_hash(raw)
        key_hash, salt = _hash_key(raw)

        await store.save("k-revoke", "user", lookup, key_hash, salt)
        assert (await store.load("k-revoke")).is_valid

        result = await store.revoke("k-revoke")
        assert result is True

        record = await store.load("k-revoke")
        assert record is not None
        assert not record.is_valid

    @pytest.mark.asyncio
    async def test_revoke_nonexistent(self, store: SQLiteApiKeyStore):
        result = await store.revoke("ghost")
        assert result is False

    @pytest.mark.asyncio
    async def test_expiry(self, store: SQLiteApiKeyStore):
        from weebot.application.ports.api_key_port import ApiKeyRecord

        expired = datetime.now(UTC) - timedelta(hours=1)
        record = ApiKeyRecord("k-exp", "user", "lh", "kh", "s", [], datetime.now(), expired)
        assert not record.is_valid

        future = datetime.now(UTC) + timedelta(days=30)
        record2 = ApiKeyRecord("k-fut", "user", "lh", "kh", "s", [], datetime.now(), future)
        assert record2.is_valid
