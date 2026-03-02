"""In-memory activity stream — ring buffer of recent agent events."""
from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import DefaultDict, Deque, Dict, List, Optional


@dataclass
class ActivityEvent:
    project_id: str
    kind: str           # job / exec / read / write / tool / message / etc.
    message: str
    timestamp: datetime = field(default_factory=datetime.now)


class ActivityStream:
    """Ring buffer of agent activity events. Thread-safe for single-writer use.

    Maintains a per-project secondary index so ``recent(project_id=...)``
    is O(k) in the number of matching results rather than O(n) over the
    entire buffer.
    """

    def __init__(self, max_size: int = 200) -> None:
        self._max_size = max_size
        self._buffer: Deque[ActivityEvent] = deque(maxlen=max_size)
        self._by_project: DefaultDict[str, Deque[ActivityEvent]] = defaultdict(deque)

    def push(self, project_id: str, kind: str, message: str) -> None:
        """Add a new event. Newest events appear first in recent()."""
        # When the main buffer is full, appendleft evicts the rightmost (oldest) event.
        # We need to remove it from the per-project index too.
        if len(self._buffer) == self._max_size:
            evicted = self._buffer[-1]  # oldest event (rightmost), about to be evicted
            proj_deque = self._by_project.get(evicted.project_id)
            if proj_deque and proj_deque and proj_deque[-1] is evicted:
                proj_deque.pop()

        event = ActivityEvent(project_id=project_id, kind=kind, message=message)
        self._buffer.appendleft(event)
        self._by_project[project_id].appendleft(event)

    def recent(self, n: int = 50,
               project_id: Optional[str] = None) -> List[ActivityEvent]:
        """Return up to n most recent events, optionally filtered by project_id."""
        if project_id is not None:
            return list(self._by_project[project_id])[:n]
        return list(self._buffer)[:n]

    def clear(self) -> None:
        """Remove all events from the buffer."""
        self._buffer.clear()
        self._by_project.clear()
