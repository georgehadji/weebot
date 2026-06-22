"""ProposalTracker — anti-pattern guard for the skill proposal loop.

Tracks skill proposals by fingerprint (normalized body hash) and
suppresses repeated proposals that haven't changed.

An anti-pattern occurs when the same skill body is proposed 3+ times
without being promoted — the distillation loop is spinning without
progress. After the suppression threshold, proposals are logged as
WARN and skipped.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ProposalTracker:
    """Tracks proposal fingerprints and detects spin loops.

    Thread-safe for synchronous access; use one instance per session.

    Args:
        suppression_threshold: Number of identical proposals before
            suppression kicks in. Default 3.
    """

    def __init__(self, suppression_threshold: int = 3) -> None:
        self._threshold = suppression_threshold
        # fingerprint → [timestamp1, timestamp2, ...]
        self._history: dict[str, list[float]] = {}
        self._suppressed_count: int = 0

    @staticmethod
    def fingerprint(body: str) -> str:
        """Compute a stable fingerprint for a skill body.

        Normalises whitespace and lowercases before hashing so that
        formatting-only changes don't produce a new fingerprint.
        """
        normalised = " ".join(body.lower().split())
        return hashlib.sha256(normalised.encode()).hexdigest()[:16]

    def record_and_check(self, fingerprint: str) -> bool:
        """Record a proposal and return whether it should proceed.

        Returns:
            True if the proposal is below the suppression threshold
            (should proceed). False if suppressed (anti-pattern).
        """
        import time
        now = time.time()
        if fingerprint not in self._history:
            self._history[fingerprint] = []
        self._history[fingerprint].append(now)

        count = len(self._history[fingerprint])
        if count >= self._threshold:
            self._suppressed_count += 1
            logger.warning(
                "ProposalTracker: anti-pattern detected — %d identical proposals "
                "for fingerprint %s (threshold=%d). Suppressing.",
                count, fingerprint, self._threshold,
            )
            return False
        return True

    def suppression_count(self) -> int:
        """Total number of suppressed proposals across all fingerprints."""
        return self._suppressed_count

    def reset(self) -> None:
        """Clear all tracked history (for test isolation)."""
        self._history.clear()
        self._suppressed_count = 0
