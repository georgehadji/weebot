"""SQLite-backed API key store — implements ApiKeyPort.

Keys are stored with two hashes:

1. ``lookup_hash`` — SHA-256 of the raw key (deterministic, indexed, fast lookup)
2. ``key_hash`` — scrypt of raw key + random salt (for verification, brute-force resistant)

The raw API key is never persisted.  Verification uses ``hmac.compare_digest``
for constant-time comparison.
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import TYPE_CHECKING

from weebot.application.ports.api_key_port import ApiKeyPort, ApiKeyRecord
from weebot.config.settings import SESSIONS_DB

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

# The hashing lives in weebot.core.api_key_crypto (pure, public) because the web
# layer verifies keys with it too. These aliases keep the CLI and older tests,
# which import the underscored names from here, working.
from weebot.core.api_key_crypto import (  # noqa: E402, F401
    generate_raw_key as _generate_raw_key,
    hash_key as _hash_key,
    lookup_hash as _lookup_hash,
    verify_key as _verify_key,
)


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

    async def save(
        self,
        key_id: str,
        principal_id: str,
        lookup_hash: str,
        key_hash: str,
        salt: str,
        scopes: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        import json

        conn = await self._ensure_open()
        now = datetime.now(UTC).isoformat()
        scopes_json = json.dumps(scopes or [])
        await conn.execute(
            """INSERT OR REPLACE INTO api_keys
               (id, principal_id, lookup_hash, key_hash, salt, scopes, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                key_id,
                principal_id,
                lookup_hash,
                key_hash,
                salt,
                scopes_json,
                now,
                expires_at.isoformat() if expires_at else None,
            ),
        )
        await conn.commit()

    async def load_by_lookup_hash(self, lookup_hash: str) -> ApiKeyRecord | None:
        conn = await self._ensure_open()
        cursor = await conn.execute("SELECT * FROM api_keys WHERE lookup_hash = ?", (lookup_hash,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    async def load(self, key_id: str) -> ApiKeyRecord | None:
        conn = await self._ensure_open()
        cursor = await conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,))
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
        now = datetime.now(UTC).isoformat()
        cursor = await conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (now, key_id)
        )
        await conn.commit()
        return cursor.rowcount > 0

    async def touch_last_used(self, key_id: str) -> None:
        conn = await self._ensure_open()
        now = datetime.now(UTC).isoformat()
        await conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, key_id))
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
            last_used_at=(
                datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None
            ),
        )

    @staticmethod
    def generate_raw_key() -> str:
        """Generate a cryptographically random API key."""
        return _generate_raw_key()
