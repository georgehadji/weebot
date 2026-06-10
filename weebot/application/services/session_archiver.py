"""SessionArchiver — marks completed/failed sessions as archived past their TTL.

Application layer — imports only Domain models and Application ports.
Never deletes sessions; sets ``context.archived = True`` so they are
excluded from active-session listings but remain queryable for audit.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session, SessionStatus

logger = logging.getLogger(__name__)


class SessionArchiver:
    """Marks completed/failed sessions as archived when they exceed their TTL.

    Args:
        state_repo: StateRepositoryPort for loading and saving sessions.
    """

    def __init__(self, state_repo: StateRepositoryPort) -> None:
        self._state_repo = state_repo

    async def run_archival(self) -> int:
        """Archive eligible sessions. Returns count archived."""
        sessions = await self._state_repo.list_sessions()
        now = datetime.now(timezone.utc)
        archived = 0

        for session in sessions:
            if not self._should_archive(session, now):
                continue
            updated = session.model_copy(update={
                "context": session.context.model_copy(update={
                    "archived": True,
                    "archived_at": now.isoformat(),
                })
            })
            await self._state_repo.save_session(updated)
            archived += 1

        logger.info("Session archival complete: %d archived", archived)
        return archived

    @staticmethod
    def _should_archive(session: Session, now: datetime) -> bool:
        """Return True if *session* should be archived.

        Conditions:
        - Not already archived
        - Status is COMPLETED or FAILED (never archive RUNNING/WAITING)
        - ``updated_at`` exceeds ``archive_ttl_days`` from session context

        Handles naive ``updated_at`` timestamps (SQLite default) by
        normalising to UTC before comparison.
        """
        if session.context.archived:
            return False  # already done
        if session.status not in (SessionStatus.COMPLETED, SessionStatus.FAILED):
            return False  # never touch RUNNING or WAITING sessions
        if session.updated_at is None:
            return False  # no timestamp to compare

        ttl = timedelta(days=session.context.archive_ttl_days)
        updated = session.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return (now - updated) > ttl
