"""Gateway session store port — persistence contract for gateway sessions.

Allows gateway sessions to survive process restarts and enables session
lookup, listing, and lifecycle management across multiple gateway platforms.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from weebot.domain.models.gateway_session import GatewaySession, GatewaySessionKey


class IGatewaySessionStorePort(Protocol):
    """Protocol for gateway session persistence.

    Implementations can be in-memory, SQLite, PostgreSQL, or any other
    storage backend.  The protocol is async to support all backends.
    """

    async def get(self, key: GatewaySessionKey) -> GatewaySession | None:
        """Retrieve a session by its composite key. Returns None if not found."""
        ...

    async def upsert(self, session: GatewaySession) -> None:
        """Create or update a session (insert-or-replace semantics)."""
        ...

    async def list(
        self,
        platform: str | None = None,
        user_id: str | None = None,
        active_only: bool = True,
    ) -> list[GatewaySession]:
        """List sessions, optionally filtered by platform or user.

        Args:
            platform: If set, only sessions for this platform.
            user_id: If set, only sessions for this user.
            active_only: If True (default), only active sessions.
        """
        ...

    async def close_session(self, key: GatewaySessionKey) -> None:
        """Mark a session as inactive (close it)."""
        ...

    async def delete(self, key: GatewaySessionKey) -> None:
        """Permanently remove a session from the store."""
        ...

    async def cleanup_expired(self, ttl_seconds: int) -> int:
        """Remove sessions that have exceeded the TTL.

        Returns:
            Number of expired sessions cleaned up.
        """
        ...


class AbstractGatewaySessionStore(ABC):
    """Abstract base class for gateway session stores.

    Provides default implementations of common methods.
    Subclasses must implement _read, _write, _delete, and _list.
    """

    @abstractmethod
    async def get(self, key: GatewaySessionKey) -> GatewaySession | None:
        ...

    @abstractmethod
    async def upsert(self, session: GatewaySession) -> None:
        ...

    @abstractmethod
    async def list(
        self,
        platform: str | None = None,
        user_id: str | None = None,
        active_only: bool = True,
    ) -> list[GatewaySession]:
        ...

    async def close_session(self, key: GatewaySessionKey) -> None:
        """Default: retrieve, mark inactive, and save."""
        session = await self.get(key)
        if session is not None:
            await self.upsert(session.close())

    async def delete(self, key: GatewaySessionKey) -> None:
        """Default: delegate to store-specific delete."""
        raise NotImplementedError("delete not implemented by this store")

    async def cleanup_expired(self, ttl_seconds: int) -> int:
        """Default: iterate active sessions and delete expired ones."""
        all_active = await self.list(active_only=True)
        removed = 0
        for session in all_active:
            if session.is_expired(ttl_seconds):
                await self.delete(session.key)
                removed += 1
        return removed
