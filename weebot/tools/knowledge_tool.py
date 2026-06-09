"""KnowledgeTool -- persistent full-text searchable knowledge base.

Notes survive Memory._trim() and process restarts.  Uses ToolRepositoryPort
for persistence.  Falls back to direct sqlite3 only when no repository is
provided (deprecated — emits a warning).

Author: Georgios-Chrysovalantis Chatzivantsidis
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import PrivateAttr

from weebot.application.ports.tool_repository_port import ToolRepositoryPort
from weebot.tools.base import BaseTool, ToolResult


class KnowledgeTool(BaseTool):
    """Persistent, searchable knowledge base that survives session restarts.

    Persists notes via injected ToolRepositoryPort.  Falls back to direct
    sqlite3 when no repository is available (deprecated).

    Actions
    -------
    add_note    -- Save a new note (title + body + optional tags/source)
    search      -- Full-text search across title, body, and tags
    get_note    -- Retrieve a single note by note_id
    list_notes  -- Browse notes (filter by project_id and/or tags)
    delete_note -- Remove a stale note by note_id
    """

    truncation_strategy: str = "boundary"
    name: str = "knowledge"
    description: str = (
        "Persistent knowledge base for storing and retrieving notes, findings, "
        "and decisions across agent sessions. Uses full-text search. "
        "See the 'action' parameter for available operations."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_note", "search", "get_note", "list_notes", "delete_note"],
                "description": "Operation to perform.",
            },
            "note_id": {
                "type": "string",
                "description": "Note ID (required for get_note / delete_note).",
            },
            "title": {
                "type": "string",
                "description": "Note title (required for add_note).",
            },
            "body": {
                "type": "string",
                "description": "Note body text (required for add_note).",
            },
            "tags": {
                "type": "string",
                "description": "Comma-separated tags (optional).",
            },
            "source": {
                "type": "string",
                "description": "Source URL or reference (optional).",
            },
            "project_id": {
                "type": "string",
                "description": "Project scope filter (optional).",
            },
            "query": {
                "type": "string",
                "description": "Full-text search query (required for search).",
            },
        },
        "required": ["action"],
    }

    _repo: ToolRepositoryPort = PrivateAttr()

    def __init__(self, repo: Optional[ToolRepositoryPort] = None):
        super().__init__()
        if repo is None:
            from weebot.application.di import Container
            c = Container()
            c.configure_defaults()
            repo = c.get(ToolRepositoryPort)  # type: ignore[assignment]
        self._repo = repo

    # ------------------------------------------------------------------
    # Public execute dispatcher
    # ------------------------------------------------------------------

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        try:
            if action == "add_note":
                return await self._add_note(kwargs)
            if action == "search":
                return await self._search(kwargs)
            if action == "get_note":
                return await self._get_note(kwargs)
            if action == "list_notes":
                return await self._list_notes(kwargs)
            if action == "delete_note":
                return await self._delete_note(kwargs)
            return ToolResult(output="", error=f"Unknown action: {action!r}")
        except Exception as exc:
            return ToolResult(output="", error=str(exc))

    # ------------------------------------------------------------------
    # Private action implementations (delegate to ToolRepositoryPort)
    # ------------------------------------------------------------------

    async def _add_note(self, kw: dict) -> ToolResult:
        title = (kw.get("title") or "").strip()
        body = (kw.get("body") or "").strip()
        if not title:
            return ToolResult(output="", error="'title' is required for add_note")
        if not body:
            return ToolResult(output="", error="'body' is required for add_note")

        project_id = kw.get("project_id") or ""
        tags_str = (kw.get("tags") or "").strip()
        tags_list = [t.strip() for t in tags_str.split(",") if t.strip()]
        source = (kw.get("source") or "").strip()

        # Prepend source to content if present
        content = body
        if source:
            content = f"[source: {source}]\n{body}"

        note_id = await self._repo.save_note(
            title=title,
            content=content,
            tags=tags_list or None,
            project_id=project_id,
        )
        return ToolResult(output=json.dumps({"note_id": note_id, "title": title}))

    async def _search(self, kw: dict) -> ToolResult:
        query = (kw.get("query") or "").strip()
        if not query:
            return ToolResult(output="", error="'query' is required for search")

        rows = await self._repo.query_notes(search=query, limit=10)
        return ToolResult(
            output=json.dumps(
                {"query": query, "count": len(rows), "results": rows},
                indent=2,
            )
        )

    async def _get_note(self, kw: dict) -> ToolResult:
        note_id = (kw.get("note_id") or "").strip()
        if not note_id:
            return ToolResult(output="", error="'note_id' is required for get_note")

        row = await self._repo.get_note(note_id)
        if row is None:
            return ToolResult(output="", error=f"Note {note_id!r} not found")
        return ToolResult(output=json.dumps(row, indent=2))

    async def _list_notes(self, kw: dict) -> ToolResult:
        project_id = kw.get("project_id") or None
        tags_filter = (kw.get("tags") or "").strip()
        tags_list = [t.strip() for t in tags_filter.split(",") if t.strip()] if tags_filter else None

        rows = await self._repo.list_notes(
            project_id=project_id or "",
            tags=tags_list,
            limit=50,
        )
        return ToolResult(
            output=json.dumps({"count": len(rows), "notes": rows}, indent=2)
        )

    async def _delete_note(self, kw: dict) -> ToolResult:
        note_id = (kw.get("note_id") or "").strip()
        if not note_id:
            return ToolResult(output="", error="'note_id' is required for delete_note")

        deleted = await self._repo.delete_note(note_id)
        if not deleted:
            return ToolResult(output="", error=f"Note {note_id!r} not found")
        return ToolResult(output=json.dumps({"deleted": note_id}))
