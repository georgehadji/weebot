"""rewind_session — undo, retry and branch a conversation (H21).

``rewind`` drops the last turns from ``Session.events`` and, when asked, puts the workspace back
to how it was before the first dropped turn changed it (the H5 checkpoint). The append-only
event journal is never rewritten: it gets a ``session_rewound`` row naming what was dropped.
``branch`` copies the events up to a point into a new session; the files are not copied.

A run in progress is refused, because its next save would write the dropped events back.
shortcut: a plan-act session rewinds at turn boundaries only, not mid-run; a mid-run cut needs
the flow checkpoint taken at that step.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from weebot.domain.models.session import Session, SessionStatus
from weebot.domain.services.session_timeline import cut_at, cut_back

if TYPE_CHECKING:
    from weebot.application.ports.event_store_port import EventStorePort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.application.ports.workspace_checkpoint_port import WorkspaceCheckpointPort

logger = logging.getLogger(__name__)

JOURNAL_EVENT = "session_rewound"


class SessionBusy(RuntimeError):
    """The session has a run in progress."""


@dataclass(frozen=True)
class RewindResult:
    session: Session
    dropped: int
    dropped_text: str  # the user message that opened the first dropped turn
    files_changed: int = 0


@dataclass
class RewindSession:
    state_repo: StateRepositoryPort
    event_store: EventStorePort | None = None
    checkpoints: WorkspaceCheckpointPort | None = None

    async def rewind(self, session_id: str, turns: int = 1, files: bool = True) -> RewindResult:
        session = await self._load(session_id)
        kept, dropped, boundary = cut_back(session.events, turns)
        files_changed = await self._restore_files(session_id, boundary.event_id, session, files)
        updated = session.replace_events(kept)
        await self.state_repo.save_session(updated)
        await self._journal(
            session_id,
            {
                "dropped_ids": [e.id for e in dropped],
                "boundary": boundary.event_id,
                "files_changed": files_changed,
            },
        )
        return RewindResult(updated, len(dropped), boundary.text, files_changed)

    async def branch(self, session_id: str, at_event_id: str) -> Session:
        session = await self._load(session_id)
        kept, _ = cut_at(session.events, at_event_id)
        new_id = str(uuid.uuid4())
        context = session.context.model_copy(deep=True)
        context.extra.update(parent_session_id=session_id, branched_from_event=at_event_id)
        child = Session(
            id=new_id,
            user_id=session.user_id,
            agent_id=session.agent_id,
            status=SessionStatus.COMPLETED,
            title=f"{session.title} (branch)" if session.title else None,
            context=context,
        ).replace_events([e.model_copy(deep=True, update={"session_id": new_id}) for e in kept])
        if not await self.state_repo.create_session(child):
            raise RuntimeError(f"session {new_id} already exists")
        return child

    async def _load(self, session_id: str) -> Session:
        session = await self.state_repo.load_session(session_id)
        if session is None:
            raise LookupError(f"Session {session_id} not found")
        if session.status == SessionStatus.RUNNING:
            raise SessionBusy(f"Session {session_id} is running; cancel it first")
        return session

    async def _restore_files(
        self, session_id: str, boundary_event_id: str, session: Session, files: bool
    ) -> int:
        """Restore the oldest checkpoint taken at or after the first dropped turn began."""
        if not files or self.checkpoints is None:
            return 0
        started = next((e.timestamp for e in session.events if e.id == boundary_event_id), None)
        if started is None:
            return 0
        try:
            refs = [
                r
                for r in await self.checkpoints.list(session_id, limit=500)
                if r.created_at >= started
            ]
            if not refs:
                return 0
            report = await self.checkpoints.restore(min(refs, key=lambda r: r.created_at))
        except Exception:
            logger.warning("rewind of %s could not restore files", session_id, exc_info=True)
            return 0
        return report.changed

    async def _journal(self, session_id: str, data: dict) -> None:
        if self.event_store is None:
            return
        try:
            await self.event_store.log_event(session_id, JOURNAL_EVENT, data)
        except Exception:
            logger.warning("rewind of %s was not journaled", session_id, exc_info=True)
