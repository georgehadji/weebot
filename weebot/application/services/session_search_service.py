"""SessionSearchService — enriched session search with goal→match→resolution bookends.

Wraps the raw FTS5 search and loads each matching session to extract:
- Goal: session title or first user message
- Resolution: last assistant message or DoneEvent content
- Match: the FTS5 snippet that triggered the hit
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single enriched search result with goal→match→resolution bookends."""
    session_id: str
    goal: str
    resolution: str
    match_summary: str
    score: float
    event_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SessionSearchService:
    """Enriched session search with bookends.

    Args:
        state_repo: Repository with ``search_sessions()``, ``load_session()``.
    """

    def __init__(self, state_repo: Any) -> None:
        self._repo = state_repo

    async def search(
        self, query: str, limit: int = 20
    ) -> list[SearchResult]:
        """Search sessions and return enriched results.

        Args:
            query: FTS5 search query string (capped at 500 chars).
            limit: Max results to return.

        Returns:
            List of SearchResult with goal→match→resolution bookends.
        """
        raw_results = await self._repo.search_sessions(query, limit=limit)
        enriched: list[SearchResult] = []

        for row in raw_results:
            session_id = row.get("session_id", "")
            try:
                session = await self._repo.load_session(session_id)
            except Exception:
                logger.debug("SessionSearchService: failed to load %s", session_id)
                continue

            if session is None:
                continue

            # Goal: session title or first user message
            goal = session.title or ""
            if not goal:
                for ev in session.events:
                    if getattr(ev, "role", "") == "user":
                        msg = getattr(ev, "message", "") or ""
                        goal = msg[:200]
                        break

            # Resolution: last assistant message or DoneEvent
            resolution = ""
            for ev in reversed(session.events):
                ev_type = getattr(ev, "type", "")
                if ev_type == "done":
                    resolution = getattr(ev, "message", "") or "Task completed"
                    break
                if getattr(ev, "role", "") == "assistant":
                    msg = getattr(ev, "message", "") or ""
                    if msg:
                        resolution = msg[:200]
                        break

            enriched.append(SearchResult(
                session_id=session_id,
                goal=goal or "(untitled)",
                resolution=resolution or "(in progress)",
                match_summary=(row.get("summary", "") or "")[:200],
                score=row.get("score", 0.0) or 0.0,
                event_count=len(session.events),
                created_at=session.created_at.isoformat() if hasattr(session, "created_at") else None,
                updated_at=session.updated_at.isoformat() if hasattr(session, "updated_at") else None,
            ))

        return enriched
