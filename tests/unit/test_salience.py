"""Tests for memory salience scoring and lifecycle sweep."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.services.salience_scorer import (
    compute_salience,
    _recency_score,
    _frequency_score,
)


# ── SalienceScorer ───────────────────────────────────────────────────────────

class TestRecencyScore:
    def test_less_than_one_hour(self):
        """Accessed within the last hour → 1.0."""
        score = _recency_score(datetime.now(timezone.utc) - timedelta(minutes=30))
        assert score == 1.0

    def test_between_one_and_24_hours(self):
        """Between 1-24 hours → linear decay 1.0-0.3."""
        score = _recency_score(datetime.now(timezone.utc) - timedelta(hours=6))
        assert 0.3 < score < 1.0

    def test_over_24_hours(self):
        """Over 24 hours → 0.1."""
        score = _recency_score(datetime.now(timezone.utc) - timedelta(hours=48))
        assert score == 0.1

    def test_none(self):
        """No last_accessed → 0.1."""
        assert _recency_score(None) == 0.1

    def test_naive_datetime_handled(self):
        """Naive datetime (no tzinfo) is handled without error."""
        naive = datetime.now(timezone.utc) - timedelta(hours=2)
        score = _recency_score(naive)
        assert isinstance(score, float)


class TestFrequencyScore:
    def test_10_plus(self):
        assert _frequency_score(10) == 1.0
        assert _frequency_score(50) == 1.0

    def test_3_to_9(self):
        assert _frequency_score(3) == 0.6
        assert _frequency_score(7) == 0.6

    def test_1_to_2(self):
        assert _frequency_score(1) == 0.3
        assert _frequency_score(2) == 0.3

    def test_zero(self):
        assert _frequency_score(0) == 0.1


class TestComputeSalience:
    def test_recent_and_frequent(self):
        """Recently accessed and frequently accessed → high salience."""
        score = compute_salience(
            access_count=15,
            last_accessed=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert score >= 0.9

    def test_old_and_rare(self):
        """Old and rarely accessed → low salience."""
        score = compute_salience(
            access_count=1,
            last_accessed=datetime.now(timezone.utc) - timedelta(days=7),
        )
        assert score <= 0.3

    def test_returns_float(self):
        score = compute_salience(access_count=5)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


# ── MemoryLifecycleService sweep ────────────────────────────────────────────

class TestLifecycleSweep:
    @pytest.fixture
    def mock_repo(self):
        repo = MagicMock()
        repo.get_low_salience_entries = AsyncMock(return_value=[
            {
                "entry_hash": "hash_old",
                "entry_text": "old memory",
                "salience": 0.1,
                "access_count": 1,
                "created_at": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
                "last_accessed": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            },
        ])
        repo.delete_memory_entries = AsyncMock(return_value=1)
        return repo

    async def test_sweep_evicts_old_entries(self, mock_repo):
        from weebot.application.services.memory_lifecycle_service import MemoryLifecycleService
        svc = MemoryLifecycleService()
        stats = await svc.sweep(repo=mock_repo)
        assert stats["checked"] == 1
        assert stats["evicted"] == 1

    async def test_sweep_empty_repo(self):
        from weebot.application.services.memory_lifecycle_service import MemoryLifecycleService
        repo = MagicMock()
        repo.get_low_salience_entries = AsyncMock(return_value=[])
        svc = MemoryLifecycleService()
        stats = await svc.sweep(repo=repo)
        assert stats["checked"] == 0
        assert stats["evicted"] == 0

    async def test_sweep_no_repo(self):
        from weebot.application.services.memory_lifecycle_service import MemoryLifecycleService
        svc = MemoryLifecycleService()
        stats = await svc.sweep(repo=None)
        assert stats == {"checked": 0, "evicted": 0}
