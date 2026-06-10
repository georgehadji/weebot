"""MemoryPressureMonitor — continuous process memory health check.

Wraps ``MemoryMonitor.check_memory()`` (sync psutil call) and classifies
the result into HEALTHY / DEGRADED / CRITICAL based on configured thresholds.

Does NOT call ``MemoryMonitor.start()`` — the HeartbeatManager owns the
polling loop. Two competing polling loops for the same resource would be a bug.
"""
from __future__ import annotations

from weebot.core.memory_monitor import MemoryMonitor, MemoryThresholds, MemoryStats
from weebot.infrastructure.observability import metrics
from .base import Monitor, MonitorReport, MonitorState


class MemoryPressureMonitor(Monitor):
    """Monitors process memory via ``MemoryMonitor.check_memory()``.

    Updates Prometheus gauges ``memory_rss_mb`` and ``memory_percent`` on
    every check (not only on transitions).
    """

    name = "memory_pressure"
    interval_seconds = 10

    def __init__(self, thresholds: MemoryThresholds | None = None) -> None:
        # Instantiate MemoryMonitor but do NOT call .start() on it.
        # We drive the polling loop ourselves from HeartbeatManager.
        self._inner = MemoryMonitor(thresholds=thresholds or MemoryThresholds())

    async def check(self) -> MonitorReport:
        """Check current memory and classify against thresholds."""
        # check_memory() is sync (psutil). For a 10s interval, blocking the
        # event loop for <1ms is acceptable. If benchmarking shows otherwise,
        # wrap with ``asyncio.to_thread()``.
        stats: MemoryStats = self._inner.check_memory()

        # Always update Prometheus gauges
        metrics.memory_rss_mb.set(stats.rss_mb)
        metrics.memory_percent.set(stats.percent)

        thresholds = self._inner.thresholds

        if stats.percent >= thresholds.critical_percent:
            return MonitorReport(
                MonitorState.CRITICAL,
                f"Memory critical: {stats.rss_mb:.0f} MB ({stats.percent:.0f}%)",
                metadata={"rss_mb": stats.rss_mb, "percent": stats.percent},
            )
        if stats.percent >= thresholds.warning_percent:
            return MonitorReport(
                MonitorState.DEGRADED,
                f"Memory warning: {stats.rss_mb:.0f} MB ({stats.percent:.0f}%)",
                metadata={"rss_mb": stats.rss_mb, "percent": stats.percent},
            )
        return MonitorReport(
            MonitorState.HEALTHY,
            f"Memory OK: {stats.rss_mb:.0f} MB",
            metadata={"rss_mb": stats.rss_mb, "percent": stats.percent},
        )
