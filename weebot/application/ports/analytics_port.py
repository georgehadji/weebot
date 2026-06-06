"""Analytics sink port — abstract interface for event analytics backends.

Implementations push agent activity events to external analytics systems:
OpenTelemetry (OTLP), Parquet files, InfluxDB, etc.  Multiple sinks can be
registered simultaneously — each receives every event.

Pattern follows :class:`TracingPort` — an ABC in the application layer so
infrastructure code can be swapped without touching domain or application logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.core.activity_stream import ActivityEvent


class AnalyticsSinkPort(ABC):
    """Abstract sink for agent activity events.

    Implementations are infrastructure adapters (e.g. OTel, Parquet).
    Registered sinks receive every event pushed to :class:`ActivityStream`.

    Usage::

        stream = ActivityStream(sinks=[otel_sink, parquet_sink])
        stream.push("proj-1", "tool", "bash: ls -la")
        # → otel_sink.push(event) and parquet_sink.push(event) are called
    """

    @abstractmethod
    async def push(self, event: "ActivityEvent") -> None:
        """Receive a single activity event.

        Must be non-blocking — implementations should buffer and flush
        asynchronously rather than perform I/O inline.

        Args:
            event: The activity event to record.
        """
        ...

    @abstractmethod
    async def flush(self) -> None:
        """Flush any buffered events to the backing store.

        Called on graceful shutdown.  Implementations must be idempotent
        (calling flush on an already-flushed or empty sink is a no-op).
        """
        ...

    async def close(self) -> None:
        """Flush and release any resources (connections, file handles).

        Default implementation calls :meth:`flush`.  Override if the sink
        holds resources that need explicit cleanup beyond flushing.
        """
        await self.flush()
