"""Commitment — a promise extracted from assistant conversation.

Represents something the agent said it would do in the future
(e.g. "I'll check back in 2 hours", "Let me monitor that for you").
Used by the CommitmentEngine to track, fulfill, and surface promises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class CommitmentStatus(Enum):
    """Lifecycle of a commitment."""

    PENDING = "pending"             # Extracted, awaiting due time
    IN_PROGRESS = "in_progress"     # Due time has arrived, follow-up in progress
    FULFILLED = "fulfilled"         # Successfully followed up / resolved
    BROKEN = "broken"               # Due time passed without follow-up
    CANCELLED = "cancelled"         # Explicitly cancelled by user or agent
    OVERDUE = "overdue"             # Past due time, no action taken yet


@dataclass
class Commitment:
    """A single extracted commitment from assistant conversation.

    Attributes:
        id: Unique identifier (UUID string).
        promise_text: The exact promise text from the response.
        context: Surrounding conversation context (previous user message).
        source_session_id: Session where the promise was made.
        source_event_id: Optional specific event ID.
        due_at: When the follow-up is expected (None = no specific time).
        status: Current lifecycle status.
        created_at: When the commitment was extracted.
        updated_at: When the commitment was last updated.
        failure_reason: Optional reason if BROKEN or CANCELLED.
    """
    id: str
    promise_text: str
    context: str
    source_session_id: str
    source_event_id: Optional[str] = None
    due_at: Optional[datetime] = None
    status: CommitmentStatus = CommitmentStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    failure_reason: Optional[str] = None
