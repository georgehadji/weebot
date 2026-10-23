"""Commitment — a promise extracted from assistant conversation.

Represents something the agent said it would do in the future
(e.g. "I'll check back in 2 hours", "Let me monitor that for you").
Used by the CommitmentEngine to track, fulfill, and surface promises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum


class CommitmentStatus(str, Enum):
    """Lifecycle of a commitment.

    `str, Enum`, like every sibling — SessionStatus, PlanStatus, StepStatus and
    AuditVerdict are all mixin enums; this one alone was not. sqlite3 binds a
    `str` subclass and refuses a bare Enum:

        sqlite3.ProgrammingError: Error binding parameter 7:
        type 'CommitmentStatus' is not supported

    So EVERY `save_commitment` raised, and `save_session` wrapped the whole
    extraction block in `except Exception: logger.debug(...)`. The commitment
    feature has never persisted a single row, and the only trace was a DEBUG
    line nobody reads.
    """

    PENDING = "pending"  # Extracted, awaiting due time
    IN_PROGRESS = "in_progress"  # Due time has arrived, follow-up in progress
    FULFILLED = "fulfilled"  # Successfully followed up / resolved
    BROKEN = "broken"  # Due time passed without follow-up
    CANCELLED = "cancelled"  # Explicitly cancelled by user or agent
    OVERDUE = "overdue"  # Past due time, no action taken yet


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
    source_event_id: str | None = None
    due_at: datetime | None = None
    status: CommitmentStatus = CommitmentStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    failure_reason: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> Commitment:
        """A Commitment from a ``commitments`` table row (ISO dates, '' for none)."""

        def _when(value) -> datetime | None:
            if not value:
                return None
            if isinstance(value, datetime):
                return value
            parsed = datetime.fromisoformat(str(value))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

        return cls(
            id=row["id"],
            promise_text=row.get("promise_text") or "",
            context=row.get("context") or "",
            source_session_id=row.get("source_session_id") or "",
            source_event_id=row.get("source_event_id") or None,
            due_at=_when(row.get("due_at")),
            status=CommitmentStatus(row.get("status") or "pending"),
            created_at=_when(row.get("created_at")) or datetime.now(UTC),
            updated_at=_when(row.get("updated_at")) or datetime.now(UTC),
            failure_reason=row.get("failure_reason") or None,
        )
