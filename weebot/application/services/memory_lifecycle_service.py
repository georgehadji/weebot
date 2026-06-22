"""MemoryLifecycleService — hot/warm/cold tier management for session memory.

Prevents unbounded growth of memory files by classifying memories into tiers:

- HOT:   Recent / frequently accessed (kept in primary storage)
- WARM:  Less frequent or older (compressed summary)
- COLD:  Stale beyond retention period (archived or deleted)

This is a pure application-layer service.  It reads memory metadata from
the MemoryPort and applies retention policies.  No infrastructure imports.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class MemoryTier(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


@dataclass
class MemoryEntry:
    """A single memory entry with lifecycle metadata."""
    key: str
    tier: MemoryTier = MemoryTier.HOT
    access_count: int = 0
    created_at: float = 0.0
    last_accessed: float = 0.0
    size_bytes: int = 0

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


# Default retention policies (in seconds)
_HOT_TTL = 3600        # 1 hour before HOT → WARM consideration
_WARM_TTL = 86400 * 7  # 7 days before WARM → COLD
_COLD_TTL = 86400 * 30 # 30 days before COLD → delete
_HOT_MIN_ACCESS = 3     # accessed 3+ times → stays HOT
_MAX_HOT_ENTRIES = 50   # max HOT entries before demotion


class MemoryLifecycleService:
    """Tiered memory lifecycle management.

    Args:
        hot_ttl: Seconds before a HOT memory is considered for demotion.
        warm_ttl: Seconds before a WARM memory is considered for COLD.
        cold_ttl: Seconds before a COLD memory is deleted.
        hot_min_access: Min access count to keep a memory HOT.
        max_hot_entries: Max HOT entries before oldest is demoted.
    """

    def __init__(
        self,
        hot_ttl: float = _HOT_TTL,
        warm_ttl: float = _WARM_TTL,
        cold_ttl: float = _COLD_TTL,
        hot_min_access: int = _HOT_MIN_ACCESS,
        max_hot_entries: int = _MAX_HOT_ENTRIES,
    ) -> None:
        self._hot_ttl = hot_ttl
        self._warm_ttl = warm_ttl
        self._cold_ttl = cold_ttl
        self._hot_min_access = hot_min_access
        self._max_hot_entries = max_hot_entries

    def classify(self, entry: MemoryEntry) -> MemoryTier:
        """Determine the appropriate tier for a memory entry.

        Rules:
        1. Entries younger than HOT_TTL → HOT (recency alone is sufficient)
        2. Entries younger than WARM_TTL → WARM
        3. Everything else → COLD (eligible for deletion)

        hot_min_access controls demotion of stale HOT entries (see sweep()),
        not initial classification — a brand-new entry is always HOT.
        """
        now = time.time()
        age = now - entry.created_at

        # HOT: within the hot TTL window
        if age < self._hot_ttl:
            return MemoryTier.HOT

        # WARM: within warm TTL
        if age < self._warm_ttl:
            return MemoryTier.WARM

        # COLD: beyond warm TTL
        return MemoryTier.COLD

    def should_retain(self, entry: MemoryEntry) -> bool:
        """Return True if *entry* should be retained, False if eligible for deletion."""
        if entry.tier == MemoryTier.HOT:
            return True
        if entry.tier == MemoryTier.WARM:
            return True
        # COLD: delete only past the cold TTL
        age = time.time() - entry.created_at
        return age < self._cold_ttl

    def demote_candidates(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """Return entries that should be demoted to a colder tier.

        Returns entries whose current tier no longer matches their classify()
        result.
        """
        candidates: list[MemoryEntry] = []
        for entry in entries:
            intended = self.classify(entry)
            if intended != entry.tier:
                candidates.append(MemoryEntry(
                    key=entry.key,
                    tier=intended,
                    access_count=entry.access_count,
                    created_at=entry.created_at,
                    last_accessed=entry.last_accessed,
                    size_bytes=entry.size_bytes,
                ))
        return candidates

    async def sweep(self, repo=None) -> dict:
        """Query low-salience entries, classify tiers, evict COLD past TTL.

        Args:
            repo: An object with ``get_low_salience_entries()`` and
                  ``delete_memory_entries()`` methods (e.g. SQLiteStateRepository).

        Returns:
            Dict with ``checked``, ``evicted`` counts.
        """
        stats: dict = {"checked": 0, "evicted": 0}
        if repo is None:
            return stats
        try:
            low_entries = await repo.get_low_salience_entries(threshold=0.3, limit=100)
        except Exception as exc:
            logger.warning("MemoryLifecycleService sweep: failed to query: %s", exc)
            return stats

        now = datetime.now(timezone.utc)
        evict_hashes: list[str] = []
        for row in low_entries:
            stats["checked"] += 1
            try:
                created = datetime.fromisoformat(row["created_at"]) if row.get("created_at") else now
                # Normalise naive datetimes to aware for comparison
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                logger.debug("MemoryLifecycleService sweep: skipping unparseable entry %s", row.get("entry_hash", "?"))
                continue
            # Use classify() to determine tier, should_retain() for eviction decision
            entry = MemoryEntry(
                key=row["entry_hash"],
                tier=MemoryTier.COLD,
                access_count=row.get("access_count", 0),
                created_at=created.timestamp(),
            )
            if not self.should_retain(entry):
                evict_hashes.append(row["entry_hash"])

        if evict_hashes:
            try:
                deleted = await repo.delete_memory_entries(evict_hashes)
                stats["evicted"] = deleted
                logger.info(
                    "MemoryLifecycleService sweep: evicted %d/%d low-salience entries",
                    deleted, len(evict_hashes),
                )
            except Exception as exc:
                logger.warning("MemoryLifecycleService sweep: eviction failed: %s", exc)

        return stats

    def enforce_hot_capacity(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """If HOT entries exceed max, demote oldest to WARM."""
        hot = [e for e in entries if e.tier == MemoryTier.HOT]
        if len(hot) <= self._max_hot_entries:
            return []

        # Sort by last_accessed ascending (oldest first)
        hot.sort(key=lambda e: e.last_accessed)
        to_demote = hot[:len(hot) - self._max_hot_entries]

        return [
            MemoryEntry(
                key=e.key,
                tier=MemoryTier.WARM,
                access_count=e.access_count,
                created_at=e.created_at,
                last_accessed=e.last_accessed,
                size_bytes=e.size_bytes,
            )
            for e in to_demote
        ]
