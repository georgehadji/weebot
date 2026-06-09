"""Session persistence adapter with retry and dead-letter fallback.

Wraps StateRepositoryPort to provide resilient session persistence.
Transient failures (WAL lock, connection pool exhaustion) are retried
with exponential backoff.  Persistent failures are written to a dead-letter
directory for manual recovery.

Usage:
    from weebot.infrastructure.persistence.session_persistence_adapter import (
        SessionPersistenceAdapter,
    )
    adapter = SessionPersistenceAdapter(repo, retry=RetryWithBackoff())
    ok = await adapter.save_session(session)
    if not ok:
        # session was dead-lettered — notify the user
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session
from weebot.utils.backoff import RetryWithBackoff, BackoffConfig

logger = logging.getLogger(__name__)

# Default retry configuration for session persistence:
# Short delays (sub-second) to avoid blocking the event loop,
# with 3 attempts before dead-lettering.
PERSISTENCE_RETRY_CONFIG = BackoffConfig(
    delays=[0.5, 1.0, 2.0],
    jitter=0.25,
)


class SessionPersistenceAdapter:
    """Wraps StateRepositoryPort with retry and dead-letter fallback.

    The adapter is designed to be used in place of a bare
    ``StateRepositoryPort`` for the ``save_session`` path.  It does
    **not** wrap read operations (``load_session``, ``list_sessions``,
    ``search_sessions``) — those should still use the underlying repo
    directly.

    Args:
        repo: The underlying StateRepositoryPort implementation.
        retry: A configured RetryWithBackoff instance.
        dead_letter_dir: Directory for dead-letter session files.
            Created automatically if it does not exist.
    """

    def __init__(
        self,
        repo: StateRepositoryPort,
        retry: Optional[RetryWithBackoff] = None,
        dead_letter_dir: Optional[Path] = None,
    ) -> None:
        self._repo = repo
        self._retry = retry or RetryWithBackoff(PERSISTENCE_RETRY_CONFIG)
        self._dead_letter_dir = dead_letter_dir or Path("./.weebot/dead_letter")
        self._dead_letter_dir.mkdir(parents=True, exist_ok=True)

    async def save_session(self, session: Session) -> bool:
        """Persist a session with retry.

        Returns:
            ``True`` if the session was successfully persisted.
            ``False`` if all retries were exhausted and the session
            was written to the dead-letter directory.

        Raises:
            Only non-retryable exceptions (per the backoff config's
            ``retryable`` predicate) are re-raised.
        """
        try:
            await self._retry.call(self._repo.save_session, session)
            return True
        except Exception as exc:
            logger.error(
                "Session %s persistence failed after retries — dead-lettering: %s",
                session.id,
                exc,
            )
            await self._write_dead_letter(session, exc)
            self._increment_failure_metric()
            return False

    async def _write_dead_letter(self, session: Session, error: Exception) -> None:
        """Write session JSON to the dead-letter directory.

        Filename: ``{session_id}_{iso_timestamp}.json``.
        The file contains the full session model dump plus error metadata
        so an operator can diagnose and replay.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        filename = f"{session.id}_{timestamp}.json"
        filepath = self._dead_letter_dir / filename

        payload = {
            "dead_lettered_at": datetime.now(timezone.utc).isoformat(),
            "error": str(error),
            "error_type": type(error).__name__,
            "session": session.model_dump(mode="json"),
        }

        try:
            filepath.write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Session %s dead-lettered to %s", session.id, filepath)
        except Exception as write_exc:
            logger.critical(
                "Failed to write dead-letter for session %s: %s",
                session.id,
                write_exc,
            )

    @staticmethod
    def _increment_failure_metric() -> None:
        """Increment the Prometheus dead-letter counter if available."""
        try:
            from weebot.infrastructure.observability import metrics as _m

            _m.session_persistence_failures_total.inc()
        except Exception:
            pass  # metrics must never break persistence

    async def replay_dead_letters(self) -> tuple[int, int]:
        """Replay all dead-lettered sessions into the repository.

        Reads every ``.json`` file in the dead-letter directory,
        reconstructs the Session, and attempts to persist it.
        Successfully replayed files are deleted; failures are left
        in place.

        Returns:
            ``(replayed, failed)`` — counts of successful and failed replays.
        """
        replayed = 0
        failed = 0

        for filepath in sorted(self._dead_letter_dir.glob("*.json")):
            try:
                payload = json.loads(filepath.read_text(encoding="utf-8"))
                session_data = payload.get("session", {})
                session = Session.model_validate(session_data)
                await self._repo.save_session(session)
                filepath.unlink()
                replayed += 1
                logger.info("Replayed dead-letter session %s", session.id)
            except Exception as exc:
                failed += 1
                logger.warning(
                    "Failed to replay dead-letter %s: %s",
                    filepath.name,
                    exc,
                )

        return replayed, failed

    @property
    def dead_letter_count(self) -> int:
        """Number of pending dead-letter files."""
        return len(list(self._dead_letter_dir.glob("*.json")))
