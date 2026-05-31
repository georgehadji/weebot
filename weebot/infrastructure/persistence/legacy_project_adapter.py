"""LegacyProjectAdapter — wraps SQLiteStateRepository to provide a
StateManager-compatible API for the MCP server and state_coordinator.

This adapter exists solely so that code written against the deprecated
StateManager can migrate to the Clean Architecture persistence layer
without a full rewrite.  It maps ProjectState/Task/Checkpoint concepts
onto Session/Event/Plan equivalents.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.event import MessageEvent
from weebot.domain.models.session import Session, SessionStatus


class LegacyProjectAdapter:
    """Compatibility wrapper around StateRepositoryPort.

    Provides the subset of StateManager's public API that is actually
    called by production code: create_project, save/load state, list
    projects, and checkpoint management mapped onto session events.
    """

    def __init__(self, repo: StateRepositoryPort) -> None:
        self._repo = repo
        self._db_path = "./weebot_sessions.db"  # informational only

    # ── project lifecycle ──────────────────────────────────────────

    async def create_project(
        self, project_id: str, description: str
    ) -> dict[str, Any]:
        """Create a new project as a Session with legacy metadata."""
        session = Session(
            id=project_id,
            user_id="legacy",
            agent_id="legacy-project-adapter",
            context={
                "description": description,
                "legacy_project": True,
                "created_via": "LegacyProjectAdapter",
            },
        )
        await self._repo.save_session(session)
        return {
            "project_id": session.id,
            "status": session.status.value,
            "description": description,
            "created_at": session.created_at.isoformat(),
        }

    async def save_state(self, project_id: str, state: dict[str, Any]) -> None:
        """Persist project state as session context."""
        session = await self._repo.load_session(project_id)
        if session is None:
            session = Session(id=project_id, user_id="legacy", agent_id="legacy")
        session = session.model_copy(
            update={"context": {**session.context, "legacy_state": state}}
        )
        await self._repo.save_session(session)

    async def load_state(self, project_id: str) -> Optional[dict[str, Any]]:
        """Load project state from session context."""
        session = await self._repo.load_session(project_id)
        if session is None:
            return None
        return {
            "project_id": session.id,
            "status": session.status.value,
            "description": session.context.get("description", ""),
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "legacy_state": session.context.get("legacy_state", {}),
        }

    async def list_projects(self) -> list[dict[str, Any]]:
        """List all projects stored as sessions with legacy_project flag."""
        sessions = await self._repo.list_sessions()
        result: list[dict[str, Any]] = []
        for s in sessions:
            if s.context.get("legacy_project"):
                result.append({
                    "project_id": s.id,
                    "status": s.status.value,
                    "description": s.context.get("description", ""),
                    "updated_at": s.updated_at.isoformat(),
                })
        return result

    async def add_checkpoint(
        self,
        project_id: str,
        description: str,
        input_prompt: Optional[str] = None,
    ) -> str:
        """Add a checkpoint as a WaitForUserEvent in the session."""
        session = await self._repo.load_session(project_id)
        if session is None:
            raise ValueError(f"Project {project_id} not found")

        chk_id = f"chk_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:6]}"
        session = session.model_copy(
            update={
                "context": {
                    **session.context,
                    "checkpoints": session.context.get("checkpoints", [])
                    + [{
                        "id": chk_id,
                        "description": description,
                        "input_prompt": input_prompt,
                        "resolved": False,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }],
                }
            }
        )
        await self._repo.save_session(session)
        return chk_id

    async def resolve_checkpoint(
        self, checkpoint_id: str, user_response: str
    ) -> None:
        """Mark a checkpoint as resolved."""
        sessions = await self._repo.list_sessions()
        for session in sessions:
            chks = session.context.get("checkpoints", [])
            for chk in chks:
                if chk.get("id") == checkpoint_id:
                    chk["resolved"] = True
                    chk["user_response"] = user_response
                    session = session.model_copy(
                        update={"context": {**session.context, "checkpoints": chks}}
                    )
                    await self._repo.save_session(session)
                    return

    async def get_pending_checkpoints(
        self, project_id: str
    ) -> list[dict[str, Any]]:
        """Get unresolved checkpoints for a project."""
        session = await self._repo.load_session(project_id)
        if session is None:
            return []
        chks = session.context.get("checkpoints", [])
        return [c for c in chks if not c.get("resolved", False)]

    # ── helper ─────────────────────────────────────────────────────

    async def close(self) -> None:
        """No-op — connection pool is managed externally."""
        pass
