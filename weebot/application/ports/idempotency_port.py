"""IdempotencyPort -- one run per (principal, Idempotency-Key) for 24 hours (H12b)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class IdempotencyPort(ABC):
    @abstractmethod
    async def get(self, key: str, principal: str) -> str | None:
        """The run id recorded for *key* by *principal* within the TTL, else None."""

    @abstractmethod
    async def put(self, key: str, principal: str, run_id: str) -> str:
        """Record *run_id* for the key unless one is recorded already; return the winner.

        Two requests with one key racing each other get the same run id back.
        """

    @abstractmethod
    async def forget(self, key: str, principal: str) -> None:
        """Drop the record, so a retry after a failed start can try again."""
