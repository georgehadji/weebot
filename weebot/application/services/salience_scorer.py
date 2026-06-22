"""SalienceScorer — computes salience scores for memory entries.

Salience (0-1) combines two components:
- Recency: how recently was the entry accessed?
- Frequency: how many times has it been accessed?

Formula: salience = 0.4 * recency_norm + 0.6 * freq_norm

Recency normalization:
- last_accessed < 1 hour ago → 1.0
- 1-24 hours → linear decay 1.0 → 0.3
- > 24 hours → 0.1

Frequency normalization:
- access_count >= 10 → 1.0
- 3-9 → 0.6
- 1-2 → 0.3
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


def compute_salience(
    access_count: int,
    last_accessed: Optional[datetime] = None,
) -> float:
    """Compute a salience score (0.0-1.0) for a memory entry.

    Args:
        access_count: Number of times the entry has been accessed.
        last_accessed: When the entry was last accessed (UTC).

    Returns:
        Salience score between 0.0 and 1.0.
    """
    recency_norm = _recency_score(last_accessed)
    freq_norm = _frequency_score(access_count)
    return round(0.4 * recency_norm + 0.6 * freq_norm, 4)


def _recency_score(last_accessed: Optional[datetime]) -> float:
    """Compute recency score (0.0-1.0) based on time since last access."""
    if last_accessed is None:
        return 0.1
    now = datetime.now(timezone.utc)
    # Make naive datetimes aware for comparison
    if last_accessed.tzinfo is None:
        last_accessed = last_accessed.replace(tzinfo=timezone.utc)
    age = now - last_accessed
    if age < timedelta(hours=1):
        return 1.0
    elif age < timedelta(hours=24):
        # Linear decay: 1.0 → 0.3 over 23 hours
        fraction = (age - timedelta(hours=1)) / timedelta(hours=23)
        return round(max(0.3, 1.0 - fraction * 0.7), 4)
    else:
        return 0.1


def _frequency_score(access_count: int) -> float:
    """Compute frequency score (0.0-1.0) based on access count."""
    if access_count >= 10:
        return 1.0
    elif access_count >= 3:
        return 0.6
    elif access_count >= 1:
        return 0.3
    return 0.1
