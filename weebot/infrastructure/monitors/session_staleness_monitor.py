"""SessionStalenessMonitor — detects RUNNING sessions with no recent updates.

Publishes ``SessionStalenessEvent`` when staleness exceeds the configured
threshold. Session count is emitted via Prometheus gauge ``session_stale_count``
on every check (not only on transitions).
"""
from __future__ import annotations

from datetime import datetime, timezone

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import SessionStatus
from weebot.infrastructure.observability import metrics
from .base import Monitor, MonitorReport, MonitorState


class SessionStalenessMonitor(Monitor):
    """Checks for RUNNING sessions with no update > threshold minutes.

    Args:
        state_repo: StateRepositoryPort for listing sessions.
        stale_threshold_minutes: Minutes without update before a session
            is considered stale.
    """

    name = "session_staleness"
    interval_seconds = 30

    STALE_THRESHOLD_MINUTES = 60

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        stale_threshold_minutes: int = STALE_THRESHOLD_MINUTES,
    ) -> None:
        self._state_repo = state_repo
        self._threshold = stale_threshold_minutes

    async def check(self) -> MonitorReport:
        """Scan running sessions and classify staleness."""
        sessions = await self._state_repo.list_sessions()
        now = datetime.now(timezone.utc)
        stale: list[str] = []

        for session in sessions:
            if session.status != SessionStatus.RUNNING:
                continue
            if session.updated_at is None:
                continue
            # Normalize to UTC (SQLite may return naive datetimes)
            updated = session.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            minutes = (now - updated).total_seconds() / 60
            if minutes > self._threshold:
                stale.append(session.id)

        # Always update the Prometheus gauge
        metrics.session_stale_count.set(len(stale))

        if not stale:
            return MonitorReport(MonitorState.HEALTHY, "No stale sessions")
        if len(stale) <= 3:
            return MonitorReport(
                MonitorState.DEGRADED,
                f"{len(stale)} stale session(s)",
                metadata={"stale_ids": stale},
            )
        return MonitorReport(
            MonitorState.CRITICAL,
            f"{len(stale)} stale sessions — possible deadlock",
            metadata={"stale_ids": stale},
        )
