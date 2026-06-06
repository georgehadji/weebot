"""In-memory activity stream — ring buffer of recent agent events.

Supports an optional list of analytics sink callables that receive every
event for external analytics (OTel, Parquet, etc.).  Sinks are duck-typed:
any object with ``async def push(event: ActivityEvent) -> None`` and
``async def flush() -> None`` works.  The canonical interface is
:class:`~weebot.application.ports.analytics_port.AnalyticsSinkPort`.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, DefaultDict, Deque, Dict, List, Optional

_log = logging.getLogger(__name__)


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

    Sinks are optional async callables that receive every event for external
    analytics.  Each sink must have ``async def push(event)`` and
    ``async def flush()``.  Errors in sinks are logged and swallowed —
    a failing sink never blocks the main event loop.

    Args:
        max_size: Maximum number of events in the ring buffer (default 200).
        sinks: Optional list of analytics sink objects (duck-typed).
    """

    def __init__(
        self,
        max_size: int = 200,
        sinks: Optional[List[Any]] = None,
    ) -> None:
        self._max_size = max_size
        self._buffer: Deque[ActivityEvent] = deque(maxlen=max_size)
        self._by_project: DefaultDict[str, Deque[ActivityEvent]] = defaultdict(deque)
        self._sinks: List[Any] = list(sinks) if sinks else []

    def add_sink(self, sink: Any) -> None:
        """Register an analytics sink to receive all future events."""
        self._sinks.append(sink)

    def push(self, project_id: str, kind: str, message: str) -> None:
        """Add a new event. Newest events appear first in recent()."""
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")

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

        # Fan out to analytics sinks (best-effort, fire-and-forget)
        for sink in self._sinks:
            try:
                # Schedule the async push; don't await — we don't block the caller.
                asyncio.ensure_future(self._safe_push(sink, event))
            except Exception:
                _log.debug("Failed to schedule sink push for %s", type(sink).__name__)

    async def _safe_push(self, sink: Any, event: ActivityEvent) -> None:
        """Push to a single sink, logging and swallowing errors."""
        try:
            await sink.push(event)
        except Exception:
            _log.warning(
                "Analytics sink %s failed on push — swallowing",
                type(sink).__name__,
                exc_info=True,
            )

    async def flush_sinks(self) -> None:
        """Flush all registered analytics sinks.

        Called on graceful shutdown.  Errors in individual sinks are logged
        and swallowed so one failing sink doesn't block others.
        """
        for sink in self._sinks:
            try:
                await sink.flush()
            except Exception:
                _log.warning(
                    "Analytics sink %s failed on flush — swallowing",
                    type(sink).__name__,
                    exc_info=True,
                )

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
