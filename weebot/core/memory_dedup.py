"""Key-value memory deduplication utility.

Normalises keys/values before storage, skips exact duplicates,
updates changed values, and logs the action taken.

Based on the MemoryManager.addMemory() pattern from
pguso/ai-agents-from-scratch (example 08).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class DedupStore:
    """Key-value store with automatic deduplication.

    Normalizes keys to lowercase/stripped for lookups. On ``set()``
    returns one of ``"added"``, ``"skipped"`` (exact duplicate), or
    ``"updated"`` (existing key, value changed). Original values are
    preserved as-is — only keys and string comparisons are normalized.

    Usage::

        store = DedupStore()
        store.set("user_name", "Alex")    # → "added"
        store.set("user_name", "Alex")    # → "skipped"
        store.set("user_name", "Bob")     # → "updated"
        store.get("user_name")            # → "Bob"
    """

    def __init__(self, max_entries: int = 1000) -> None:
        self._data: dict[str, Any] = {}          # normalized key → original value
        self._stored: dict[str, Any] = {}         # normalized key → normalized value (for dedup comparison)
        self._timestamps: dict[str, int] = {}    # monotonic counter for tiebreaker
        self._max_entries = max_entries
        self._clock: int = 0

    def _tick(self) -> int:
        """Return a monotonically increasing clock value."""
        self._clock += 1
        return self._clock

    def set(self, key: str, value: Any, source: str = "agent") -> str:
        """Store a key-value pair with deduplication.

        Returns:
            ``"added"`` — new entry stored.
            ``"skipped"`` — exact duplicate, not stored.
            ``"updated"`` — existing key with changed value.
        """
        norm_key = self._normalize(key)
        # Normalize only for comparison; store the original value
        norm_value = self._normalize(value) if isinstance(value, str) else value

        if norm_key in self._data:
            # Compare against a stored normalized version for dedup
            existing = self._stored.get(norm_key)
            if existing is not None and existing == norm_value:
                logger.debug("DedupStore: skipped duplicate key '%s'", norm_key)
                return "skipped"
            # Update both the original value and the normalized comparison cache
            self._data[norm_key] = value
            self._stored[norm_key] = norm_value
            self._timestamps[norm_key] = self._tick()
            logger.debug("DedupStore: updated key '%s'", norm_key)
            return "updated"

        # Evict oldest if at capacity
        if len(self._data) >= self._max_entries:
            oldest = min(self._timestamps, key=lambda k: self._timestamps[k])
            del self._data[oldest]
            del self._stored[oldest]
            del self._timestamps[oldest]

        self._data[norm_key] = value
        self._stored[norm_key] = norm_value
        self._timestamps[norm_key] = self._tick()
        logger.debug("DedupStore: added key '%s'", norm_key)
        return "added"

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key (case-insensitive)."""
        return self._data.get(self._normalize(key), default)

    def has(self, key: str) -> bool:
        """Check if a key exists (case-insensitive)."""
        return self._normalize(key) in self._data

    def remove(self, key: str) -> bool:
        """Remove a key. Returns True if it existed."""
        norm_key = self._normalize(key)
        if norm_key in self._data:
            del self._data[norm_key]
            del self._stored[norm_key]
            del self._timestamps[norm_key]
            return True
        return False

    def clear(self) -> None:
        """Remove all entries."""
        self._data.clear()
        self._stored.clear()
        self._timestamps.clear()

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of all stored data."""
        return dict(self._data)

    @property
    def size(self) -> int:
        """Number of stored entries."""
        return len(self._data)

    @staticmethod
    def _normalize(key: str) -> str:
        return key.strip().lower()
