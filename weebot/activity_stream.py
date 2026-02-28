"""In-memory activity stream — ring buffer of recent agent events."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, List, Optional


@dataclass
class ActivityEvent:
    project_id: str
    kind: str           # job / exec / read / write / tool / message / etc.
    message: str
    timestamp: datetime = field(default_factory=datetime.now)


class ActivityStream:
    """Ring buffer of agent activity events. Thread-safe for single-writer use."""

    def __init__(self, max_size: int = 200) -> None:
        self._buffer: Deque[ActivityEvent] = deque(maxlen=max_size)

    def push(self, project_id: str, kind: str, message: str) -> None:
        """Add a new event. Newest events appear first in recent()."""
        self._buffer.appendleft(ActivityEvent(
            project_id=project_id,
            kind=kind,
            message=message,
        ))

    def recent(self, n: int = 50,
               project_id: Optional[str] = None) -> List[ActivityEvent]:
        """Return up to n most recent events, optionally filtered by project_id."""
        events = list(self._buffer)
        if project_id is not None:
            events = [e for e in events if e.project_id == project_id]
        return events[:n]

    def clear(self) -> None:
        """Remove all events from the buffer."""
        self._buffer.clear()
