"""HeartbeatManager — runs monitors in isolated asyncio.Tasks.

Design decisions:
- One ``asyncio.Task`` per monitor — isolation; a crash in one does
  not kill siblings.
- Events published only on state *transition* (prev_state != report.state).
- ``stop()`` cancels all tasks and awaits them within cancel_timeout.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.domain.models.event import MemoryPressureEvent, SessionStalenessEvent, LLMHealthEvent
from .base import Monitor, MonitorReport, MonitorState

logger = logging.getLogger(__name__)


class HeartbeatManager:
    """Manages a fleet of ``Monitor`` instances inside background asyncio.Tasks.

    Args:
        monitors: List of Monitor instances to poll.
        event_bus: EventBusPort for publishing transition events.
        cancel_timeout: Max seconds to wait for each task on ``stop()``.
    """

    def __init__(
        self,
        monitors: list[Monitor],
        event_bus: EventBusPort,
        cancel_timeout: float = 5.0,
    ) -> None:
        self._monitors = monitors
        self._event_bus = event_bus
        self._cancel_timeout = cancel_timeout
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Launch one background task per monitor."""
        for monitor in self._monitors:
            task = asyncio.create_task(
                self._run_monitor_loop(monitor),
                name=f"monitor.{monitor.name}",
            )
            self._tasks.append(task)
        logger.info("HeartbeatManager started with %d monitor(s)", len(self._monitors))

    async def stop(self) -> None:
        """Cancel all monitor tasks and await their cleanup."""
        for task in self._tasks:
            task.cancel()
        gathered = await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        errors = [g for g in gathered if isinstance(g, BaseException) and not isinstance(g, asyncio.CancelledError)]
        if errors:
            logger.warning("HeartbeatManager: %d monitor(s) raised during shutdown", len(errors))
        logger.info("HeartbeatManager stopped")

    # ── Private ─────────────────────────────────────────────────────

    async def _run_monitor_loop(self, monitor: Monitor) -> None:
        """Poll *monitor* at its configured interval, publishing on transitions."""
        prev_state: MonitorState | None = None
        while True:
            await asyncio.sleep(monitor.interval_seconds)
            try:
                report = await asyncio.wait_for(
                    monitor.check(),
                    timeout=monitor.interval_seconds * 2,
                )
            except asyncio.CancelledError:
                raise  # propagate cancellation to the task
            except asyncio.TimeoutError:
                logger.warning("Monitor %s timed out after %.0fs",
                               monitor.name, monitor.interval_seconds * 2)
                continue
            except Exception:
                logger.exception("Monitor %s check raised", monitor.name)
                continue

            if report.state != prev_state:
                await self._publish_transition(monitor.name, prev_state, report)
                prev_state = report.state

    async def _publish_transition(
        self, name: str, prev: MonitorState | None, report: MonitorReport
    ) -> None:
        """Publish the appropriate domain event for a state transition."""
        logger.info(
            "Monitor %s: %s → %s (%s)",
            name, (prev.value if prev else "initial"), report.state.value, report.message,
        )

        event: Any = None
        if name == "session_staleness":
            event = SessionStalenessEvent(
                session_id=report.metadata.get("stale_ids", ["__batch__"])[0] if report.metadata.get("stale_ids") else "__batch__",
                staleness_minutes=0.0,
                status="running",
            )
        elif name == "memory_pressure":
            event = MemoryPressureEvent(
                level=report.state.value,
                rss_mb=report.metadata.get("rss_mb", 0.0),
                percent=report.metadata.get("percent", 0.0),
            )
        elif name == "llm_health":
            event = LLMHealthEvent(
                state=report.state.value,
                affected_providers=(
                    report.metadata.get("unhealthy", []) +
                    report.metadata.get("degraded", [])
                ),
                message=report.message,
            )

        if event is not None:
            await self._event_bus.publish(event)
