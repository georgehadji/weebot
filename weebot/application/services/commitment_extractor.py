"""CommitmentExtractor — extracts promises from assistant conversation text.

Uses regex patterns to detect common commitment phrases and parses
temporal expressions to estimate due dates.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional
from uuid import uuid4

from weebot.domain.models.commitment import Commitment, CommitmentStatus

logger = logging.getLogger(__name__)

# Regex patterns for commitment detection.
# Each pattern has a name group and captures the promise text.
_COMMITMENT_PATTERNS: list[tuple[str, str]] = [
    # Follow-up / check-back promises
    (r"(I'?ll|I will|Let me)\s+(check\s+(back|in)|follow\s+(up|back)|"
     r"get\s+back\s+to\s+(you|ya)|report\s+back|circle\s+back)",
     "follow_up"),
    # Monitoring / watching
    (r"(I'?ll|I will|Let me)\s+(monitor|keep\s+(an?\s+)?eye\s+on|"
     r"watch|track|keep\s+(tabs?\s+)?on)",
     "monitor"),
    # Notification / updates
    (r"(I'?ll|I will|Let me)\s+(notify|update|inform|let\s+(you|ya)\s+know)",
     "notify"),
    # Investigation / research
    (r"(I'?ll|I will|Let me)\s+(look\s+into|investigate|research|"
     r"dig\s+(into|deeper)|find\s+out|check\s+on)",
     "investigate"),
    # "I'll see / I'll find / I'll get"
    (r"(I'?ll|I will)\s+(see\s+(what|if|how)|find\s+out\s+(what|if|whether)|"
     r"get\s+(you|ya)\s+(the|those|that))",
     "investigate"),
]

def _parse_due_at(text: str) -> Optional[datetime]:
    """Parse a due_at datetime from temporal phrases in *text*.

    Returns None if no temporal phrase is found.
    """
    now = datetime.now(timezone.utc)
    text_lower = text.lower()

    # "in X hours/minutes/days/weeks"
    m = re.search(r"in\s+(\d+)\s+(hour|hours|minute|minutes|day|days|week|weeks)", text_lower)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("hour"):
            return now + timedelta(hours=amount)
        elif unit.startswith("minute"):
            return now + timedelta(minutes=amount)
        elif unit.startswith("day"):
            return now + timedelta(days=amount)
        elif unit.startswith("week"):
            return now + timedelta(weeks=amount)

    # "in a hour / in a day / in a week"
    m = re.search(r"in\s+a[n]?\s+(hour|day|week)", text_lower)
    if m:
        unit = m.group(1)
        if unit == "hour":
            return now + timedelta(hours=1)
        elif unit == "day":
            return now + timedelta(days=1)
        elif unit == "week":
            return now + timedelta(weeks=1)

    # "tomorrow"
    if re.search(r"\btomorrow\b", text_lower):
        return now + timedelta(days=1)

    # "next week / next month"
    m = re.search(r"\bnext\s+(week|month)\b", text_lower)
    if m:
        unit = m.group(1)
        if unit == "week":
            return now + timedelta(weeks=1)
        elif unit == "month":
            return now + timedelta(days=30)

    return None


def extract_commitments(
    assistant_text: str,
    context: str = "",
    source_session_id: str = "",
    source_event_id: Optional[str] = None,
) -> list[Commitment]:
    """Extract commitments (promises) from assistant response text.

    Args:
        assistant_text: The assistant's response text to scan.
        context: Optional preceding user message for context.
        source_session_id: Session where the promise was made.
        source_event_id: Optional event ID.

    Returns:
        List of extracted Commitment objects (empty if none found).
    """
    if not assistant_text or not assistant_text.strip():
        return []

    text_lower = assistant_text.lower()
    found: list[Commitment] = []

    for pattern, commitment_type in _COMMITMENT_PATTERNS:
        for match in re.finditer(pattern, text_lower, re.IGNORECASE):
            promise_text = match.group(0).strip()
            due_at = _parse_due_at(assistant_text)

            commitment = Commitment(
                id=str(uuid4()),
                promise_text=promise_text,
                context=(context or "")[:500],
                source_session_id=source_session_id,
                source_event_id=source_event_id,
                due_at=due_at,
                status=CommitmentStatus.PENDING,
            )
            found.append(commitment)

            logger.debug(
                "Extracted commitment: %r (type=%s, due_at=%s)",
                promise_text, commitment_type, due_at,
            )

    return found
