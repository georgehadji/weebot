"""SQLite-backed API key store — implements ApiKeyPort.

Keys are stored with two hashes:

1. ``lookup_hash`` — SHA-256 of the raw key (deterministic, indexed, fast lookup)
2. ``key_hash`` — scrypt of raw key + random salt (for verification, brute-force resistant)

The raw API key is never persisted.  Verification uses ``hmac.compare_digest``
for constant-time comparison.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from weebot.application.ports.api_key_port import ApiKeyPort, ApiKeyRecord
from weebot.config.settings import SESSIONS_DB

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

# scrypt parameters — balanced for API key verification.
# API keys have high entropy (48 bytes urlsafe base64), so scrypt's
# primary value is slowing brute-force on leaked hashes.
_SCRYPT_N = 2**14  # CPU/memory cost (16384)
_SCRYPT_R = 8      # block size
_SCRYPT_P = 1      # parallelization factor
_SCRYPT_DKLEN = 32 # output length in bytes
_SALT_BYTES = 32   # salt length for scrypt


def _lookup_hash(raw_key: str) -> str:
    """SHA-256 of the raw key — deterministic, used for record lookup."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _hash_key(raw_key: str) -> tuple[str, str]:
    """Hash an API key with a random salt using scrypt.

    Returns (scrypt_hash_hex, salt_hex).
    """
    salt = os.urandom(_SALT_BYTES)
    key_bytes = raw_key.encode("utf-8")
    dk = hashlib.scrypt(
        key_bytes, salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
    )
    return dk.hex(), salt.hex()


def _verify_key(raw_key: str, stored_hash_hex: str, salt_hex: str) -> bool:
    """Verify a raw key against a stored scrypt hash + salt.

    Uses hmac.compare_digest for constant-time comparison.
    """
    salt = bytes.fromhex(salt_hex)
    key_bytes = raw_key.encode("utf-8")
    dk = hashlib.scrypt(
        key_bytes, salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
    )
    return hmac.compare_digest(dk.hex(), stored_hash_hex)


class SQLiteApiKeyStore(ApiKeyPort):
    """Sqlite-backed API key store."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path or SESSIONS_DB)
        self._conn: aiosqlite.Connection | None = None

    async def _ensure_open(self) -> aiosqlite.Connection:
        if self._conn is None:
            import aiosqlite
            self._conn = await aiosqlite.connect(str(self._db_path))
            self._conn.row_factory = aiosqlite.Row  # type: ignore[attr-defined]
            await self._conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    lookup_hash TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    scopes TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    revoked_at TEXT,
                    last_used_at TEXT
                )
            """)
            await self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_api_keys_lookup
                ON api_keys(lookup_hash)
            """)
            await self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_api_keys_principal
                ON api_keys(principal_id)
            """)
            await self._conn.commit()
        return self._conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def save(self, key_id: str, principal_id: str,
                   lookup_hash: str, key_hash: str, salt: str,
                   scopes: list[str] | None = None,
                   expires_at: datetime | None = None) -> None:
        import json
        conn = await self._ensure_open()
        now = datetime.now(timezone.utc).isoformat()
        scopes_json = json.dumps(scopes or [])
        await conn.execute(
            """INSERT OR REPLACE INTO api_keys
               (id, principal_id, lookup_hash, key_hash, salt, scopes, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (key_id, principal_id, lookup_hash, key_hash, salt,
             scopes_json, now, expires_at.isoformat() if expires_at else None),
        )
        await conn.commit()

    async def load_by_lookup_hash(self, lookup_hash: str) -> Optional[ApiKeyRecord]:
        conn = await self._ensure_open()
        cursor = await conn.execute(
            "SELECT * FROM api_keys WHERE lookup_hash = ?", (lookup_hash,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    async def load(self, key_id: str) -> Optional[ApiKeyRecord]:
        conn = await self._ensure_open()
        cursor = await conn.execute(
            "SELECT * FROM api_keys WHERE id = ?", (key_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    async def list_by_principal(self, principal_id: str) -> list[ApiKeyRecord]:
        conn = await self._ensure_open()
        cursor = await conn.execute(
            "SELECT * FROM api_keys WHERE principal_id = ? ORDER BY created_at DESC",
            (principal_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_record(r) for r in rows]

    async def revoke(self, key_id: str) -> bool:
        conn = await self._ensure_open()
        now = datetime.now(timezone.utc).isoformat()
        cursor = await conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (now, key_id),
        )
        await conn.commit()
        return cursor.rowcount > 0

    async def touch_last_used(self, key_id: str) -> None:
        conn = await self._ensure_open()
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
            (now, key_id),
        )
        await conn.commit()

    def _row_to_record(self, row) -> ApiKeyRecord:
        import json
        return ApiKeyRecord(
            id=row["id"],
            principal_id=row["principal_id"],
            lookup_hash=row["lookup_hash"],
            key_hash=row["key_hash"],
            salt=row["salt"],
            scopes=json.loads(row["scopes"] or "[]"),
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            revoked_at=datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None,
            last_used_at=datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None,
        )

    @staticmethod
    def generate_raw_key() -> str:
        """Generate a cryptographically random API key."""
        return f"wb_{secrets.token_urlsafe(48)}"
