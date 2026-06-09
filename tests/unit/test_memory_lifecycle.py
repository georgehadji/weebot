"""Tests for Phase 8: MemoryLifecycleService."""
import pytest
import time

from weebot.application.services.memory_lifecycle_service import (
    MemoryLifecycleService,
    MemoryEntry,
    MemoryTier,
)


@pytest.fixture
def service():
    return MemoryLifecycleService(
        hot_ttl=3600,
        warm_ttl=86400 * 7,
        cold_ttl=86400 * 30,
        hot_min_access=3,
        max_hot_entries=50,
    )


@pytest.fixture
def fresh_hot_entry():
    return MemoryEntry(
        key="recent_memory",
        tier=MemoryTier.HOT,
        access_count=5,
        created_at=time.time() - 100,  # 100 seconds ago
        last_accessed=time.time() - 10,
        size_bytes=1000,
    )


def test_classify_hot_recent_frequent(service):
    """Recent + frequently accessed -> HOT."""
    entry = MemoryEntry(
        key="test",
        access_count=5,
        created_at=time.time() - 100,
    )
    tier = service.classify(entry)
    assert tier == MemoryTier.HOT


def test_classify_hot_recent_low_access(service):
    """Recent but low access -> HOT (within TTL)."""
    entry = MemoryEntry(
        key="test",
        access_count=0,
        created_at=time.time() - 100,
    )
    tier = service.classify(entry)
    assert tier == MemoryTier.HOT


def test_classify_warm_old(service):
    """Old entry with low access -> WARM."""
    entry = MemoryEntry(
        key="test",
        access_count=0,
        created_at=time.time() - 7200,  # 2 hours ago (past HOT_TTL)
    )
    tier = service.classify(entry)
    assert tier == MemoryTier.WARM


def test_classify_cold_very_old(service):
    """Very old entry -> COLD."""
    entry = MemoryEntry(
        key="test",
        access_count=0,
        created_at=time.time() - 86400 * 14,  # 14 days ago
    )
    tier = service.classify(entry)
    assert tier == MemoryTier.COLD


def test_should_retain_hot(service, fresh_hot_entry):
    """HOT entries are always retained."""
    assert service.should_retain(fresh_hot_entry)


def test_should_retain_warm(service):
    """WARM entries are retained."""
    entry = MemoryEntry(key="warm", tier=MemoryTier.WARM)
    assert service.should_retain(entry)


def test_should_not_retain_cold_past_ttl(service):
    """COLD past cold_ttl -> not retained."""
    entry = MemoryEntry(
        key="stale",
        tier=MemoryTier.COLD,
        created_at=time.time() - 86400 * 60,  # 60 days
    )
    assert not service.should_retain(entry)


def test_demote_candidates_detects_change(service, fresh_hot_entry):
    """Entry classified as WARM but tagged HOT -> demotion candidate."""
    entries = [fresh_hot_entry]
    # Keep fresh_hot_entry as is — it should stay HOT
    candidates = service.demote_candidates(entries)
    assert len(candidates) == 0  # It's still within HOT TTL


def test_demote_candidates_old_hot_to_warm(service):
    """Old entry tagged HOT -> demoted to WARM."""
    entry = MemoryEntry(
        key="old_hot",
        tier=MemoryTier.HOT,
        access_count=1,
        created_at=time.time() - 7200,  # 2 hours
    )
    candidates = service.demote_candidates([entry])
    assert len(candidates) >= 1
    assert candidates[0].tier == MemoryTier.WARM


def test_enforce_hot_capacity(service):
    """More than max_hot_entries -> oldest demoted."""
    entries = [
        MemoryEntry(
            key=f"hot_{i}",
            tier=MemoryTier.HOT,
            last_accessed=time.time() - (100 - i),
        )
        for i in range(55)  # 55 entries, max 50
    ]
    demoted = service.enforce_hot_capacity(entries)
    assert len(demoted) == 5  # 5 oldest demoted
    assert all(d.tier == MemoryTier.WARM for d in demoted)


def test_enforce_hot_capacity_under_limit(service):
    """Under max_hot_entries -> no demotion."""
    entries = [
        MemoryEntry(key=f"hot_{i}", tier=MemoryTier.HOT)
        for i in range(30)
    ]
    demoted = service.enforce_hot_capacity(entries)
    assert len(demoted) == 0


def test_memory_entry_age_property():
    """age_seconds returns positive value."""
    entry = MemoryEntry(key="test", created_at=time.time() - 3600)
    assert entry.age_seconds >= 3500  # ~1 hour
