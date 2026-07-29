"""ApiKeyPort — abstract interface for API key persistence and validation.

Decouples credential storage (SQLite, files, cloud) from the auth middleware
so multi-principal identity can be swapped without touching HTTP logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class ApiKeyRecord:
    """A stored API key record.

    The raw key is never persisted.  Two hashes are stored:

    - ``lookup_hash`` — SHA-256 of the raw key (deterministic, indexed, used for lookup)
    - ``key_hash`` — scrypt of raw key with a random salt (stored, used for verification)

    The ``salt`` is stored alongside so verification can recompute the same scrypt hash.
    """

    def __init__(
        self,
        id: str,
        principal_id: str,
        lookup_hash: str,
        key_hash: str,
        salt: str | None = None,
        scopes: list[str] | None = None,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
        revoked_at: datetime | None = None,
        last_used_at: datetime | None = None,
    ) -> None:
        self.id = id
        self.principal_id = principal_id
        self.lookup_hash = lookup_hash
        self.key_hash = key_hash
        self.salt = salt or ""
        self.scopes = scopes or []
        self.created_at = created_at or datetime.min
        self.expires_at = expires_at
        self.revoked_at = revoked_at
        self.last_used_at = last_used_at

    @property
    def is_valid(self) -> bool:
        """Return True if the key is not expired and not revoked."""
        now = datetime.now()
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None:
            expires = self.expires_at
            if expires.tzinfo is not None:
                from datetime import timezone
                now = datetime.now(timezone.utc)
            if now > expires:
                return False
        return True


class ApiKeyPort(ABC):
    """Abstract interface for API key lifecycle management."""

    @abstractmethod
    async def save(self, key_id: str, principal_id: str,
                   lookup_hash: str, key_hash: str, salt: str,
                   scopes: list[str] | None = None,
                   expires_at: datetime | None = None) -> None:
        """Store a new API key record.

        Args:
            key_id: Unique identifier for this key.
            principal_id: The user/service this key belongs to.
            lookup_hash: SHA-256 of the raw key (deterministic, for lookup).
            key_hash: scrypt hash of the raw key + salt (for verification).
            salt: Random salt used to derive key_hash.
            scopes: Optional list of permission scopes.
            expires_at: Optional expiration timestamp.
        """
        ...

    @abstractmethod
    async def load_by_lookup_hash(self, lookup_hash: str) -> Optional[ApiKeyRecord]:
        """Look up an API key record by its SHA-256 lookup hash.

        Returns None if no matching key exists.
        """
        ...

    @abstractmethod
    async def load(self, key_id: str) -> Optional[ApiKeyRecord]:
        """Load a key record by its ID."""
        ...

    @abstractmethod
    async def list_by_principal(self, principal_id: str) -> list[ApiKeyRecord]:
        """List all key records for a given principal."""
        ...

    @abstractmethod
    async def revoke(self, key_id: str) -> bool:
        """Revoke a key. Returns True if the key existed and was revoked."""
        ...

    @abstractmethod
    async def touch_last_used(self, key_id: str) -> None:
        """Update the ``last_used_at`` timestamp for a key."""
        ...
