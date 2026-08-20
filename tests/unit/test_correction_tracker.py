"""Tests for CorrectionTracker (ICM Phase C — edit-source principle).

Verifies: recurring same-category corrections cross PATTERN_THRESHOLD and
are surfaced; heuristic classification buckets corrections sensibly when
no LLM is configured.
"""

from __future__ import annotations

import pytest

from weebot.application.services.correction_tracker import CorrectionTracker
from weebot.domain.models.correction import CorrectionRecord
from weebot.domain.models.plan import Step


class _FakeStateRepo:
    """In-memory stand-in for StateRepositoryPort's correction methods."""

    def __init__(self) -> None:
        self.records: list[CorrectionRecord] = []

    async def save_correction_record(self, record: CorrectionRecord) -> None:
        self.records.append(record)

    async def count_corrections_by_category(self, category: str) -> int:
        return sum(1 for r in self.records if r.correction_category == category)

    async def get_correction_patterns(self, min_count: int = 3) -> list[dict]:
        counts: dict[str, int] = {}
        for r in self.records:
            counts[r.correction_category] = counts.get(r.correction_category, 0) + 1
        return [{"category": cat, "count": n} for cat, n in counts.items() if n >= min_count]


def _step(step_id: str = "s1", desc: str = "write something") -> Step:
    return Step(id=step_id, description=desc)


@pytest.mark.asyncio
async def test_record_correction_below_threshold_returns_none():
    repo = _FakeStateRepo()
    tracker = CorrectionTracker(state_repo=repo)

    # Same-length rewrites → heuristic classifies as "accuracy".
    r1 = await tracker.record_correction(
        session_id="sess1", step=_step(), original_output="X" * 100, corrected_output="Y" * 100
    )
    r2 = await tracker.record_correction(
        session_id="sess1", step=_step(), original_output="X" * 100, corrected_output="Y" * 100
    )
    assert r1 is None
    assert r2 is None
    assert len(repo.records) == 2


@pytest.mark.asyncio
async def test_record_correction_at_threshold_returns_pattern():
    repo = _FakeStateRepo()
    tracker = CorrectionTracker(state_repo=repo)

    result = None
    for _ in range(tracker.PATTERN_THRESHOLD):
        result = await tracker.record_correction(
            session_id="sess1", step=_step(), original_output="X" * 100, corrected_output="Y" * 100
        )
    assert result is not None
    assert isinstance(result, CorrectionRecord)
    assert result.correction_category == "accuracy"


@pytest.mark.asyncio
async def test_heuristic_classification_scope_for_shortened_output():
    repo = _FakeStateRepo()
    tracker = CorrectionTracker(state_repo=repo)
    category = tracker._classify_heuristic("X" * 100, "Y" * 50)  # 50% of original
    assert category == "scope"


@pytest.mark.asyncio
async def test_heuristic_classification_missing_info_for_expanded_output():
    repo = _FakeStateRepo()
    tracker = CorrectionTracker(state_repo=repo)
    category = tracker._classify_heuristic("X" * 100, "Y" * 200)  # 200% of original
    assert category == "missing_info"


@pytest.mark.asyncio
async def test_heuristic_classification_accuracy_for_similar_length():
    repo = _FakeStateRepo()
    tracker = CorrectionTracker(state_repo=repo)
    category = tracker._classify_heuristic("X" * 100, "Y" * 105)  # ~same length
    assert category == "accuracy"


@pytest.mark.asyncio
async def test_get_recurring_patterns_reflects_repo():
    repo = _FakeStateRepo()
    tracker = CorrectionTracker(state_repo=repo)
    for _ in range(3):
        await tracker.record_correction(
            session_id="sess1", step=_step(), original_output="X" * 100, corrected_output="Y" * 100
        )
    patterns = await tracker.get_recurring_patterns(min_count=3)
    assert any(p["category"] == "accuracy" and p["count"] >= 3 for p in patterns)


@pytest.mark.asyncio
async def test_different_categories_tracked_independently():
    repo = _FakeStateRepo()
    tracker = CorrectionTracker(state_repo=repo)

    # 2x "scope" (shortened), 2x "missing_info" (expanded) — neither hits threshold of 3.
    r1 = await tracker.record_correction("sess1", _step(), "X" * 100, "Y" * 50)
    r2 = await tracker.record_correction("sess1", _step(), "X" * 100, "Y" * 50)
    r3 = await tracker.record_correction("sess1", _step(), "X" * 100, "Y" * 200)
    r4 = await tracker.record_correction("sess1", _step(), "X" * 100, "Y" * 200)
    assert r1 is None and r2 is None and r3 is None and r4 is None
