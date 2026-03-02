"""KnowledgeTool -- persistent full-text searchable knowledge base.

Uses SQLite FTS5 to store and retrieve notes, findings, and decisions across
agent sessions. Notes survive Memory._trim() and process restarts.

Author: Georgios-Chrysovalantis Chatzivantsidis
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from weebot.tools.base import BaseTool, ToolResult


class KnowledgeTool(BaseTool):
    """Persistent, searchable knowledge base that survives session restarts.

    Stores notes in an SQLite FTS5 table so the agent can accumulate
    research findings and retrieve them by keyword across sessions.

    Actions
    -------
    add_note    -- Save a new note (title + body + optional tags/source)
    search      -- Full-text search across title, body, and tags
    get_note    -- Retrieve a single note by note_id
    list_notes  -- Browse notes (filter by project_id and/or tags)
    delete_note -- Remove a stale note by note_id
    """

    name: str = "knowledge"
    description: str = (
        "Persistent knowledge base for storing and retrieving notes, findings, "
        "and decisions across agent sessions. Uses SQLite FTS5 full-text search. "
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

    db_path: str = "projects.db"

    def model_post_init(self, __context: Any) -> None:
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the FTS5 kb_notes table if it does not exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS kb_notes USING fts5(
                    note_id    UNINDEXED,
                    project_id UNINDEXED,
                    created_at UNINDEXED,
                    source     UNINDEXED,
                    title,
                    body,
                    tags
                )
            """)
            conn.commit()

    # ------------------------------------------------------------------
    # Public execute dispatcher
    # ------------------------------------------------------------------

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        try:
            if action == "add_note":
                return self._add_note(kwargs)
            if action == "search":
                return self._search(kwargs)
            if action == "get_note":
                return self._get_note(kwargs)
            if action == "list_notes":
                return self._list_notes(kwargs)
            if action == "delete_note":
                return self._delete_note(kwargs)
            return ToolResult(output="", error=f"Unknown action: {action!r}")
        except Exception as exc:
            return ToolResult(output="", error=str(exc))

    # ------------------------------------------------------------------
    # Private action implementations
    # ------------------------------------------------------------------

    def _add_note(self, kw: dict) -> ToolResult:
        title = (kw.get("title") or "").strip()
        body = (kw.get("body") or "").strip()
        if not title:
            return ToolResult(output="", error="'title' is required for add_note")
        if not body:
            return ToolResult(output="", error="'body' is required for add_note")

        note_id = str(uuid.uuid4())[:8]
        project_id = kw.get("project_id") or ""
        tags = kw.get("tags") or ""
        source = kw.get("source") or ""
        created_at = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO kb_notes
                   (note_id, project_id, created_at, source, title, body, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (note_id, project_id, created_at, source, title, body, tags),
            )
            conn.commit()

        return ToolResult(output=json.dumps({"note_id": note_id, "title": title}))

    def _search(self, kw: dict) -> ToolResult:
        query = (kw.get("query") or "").strip()
        if not query:
            return ToolResult(output="", error="'query' is required for search")
        project_id = kw.get("project_id") or None

        params: list = [query]
        sql = (
            "SELECT note_id, project_id, created_at, title, tags, source, "
            "substr(body, 1, 200) AS excerpt "
            "FROM kb_notes WHERE kb_notes MATCH ?"
        )
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += " ORDER BY rank LIMIT 10"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(sql, params)
                rows = cursor.fetchall()
            except sqlite3.OperationalError as exc:
                return ToolResult(output="", error=f"Search error: {exc}")

        results = [dict(r) for r in rows]
        return ToolResult(
            output=json.dumps(
                {"query": query, "count": len(results), "results": results},
                indent=2,
            )
        )

    def _get_note(self, kw: dict) -> ToolResult:
        note_id = (kw.get("note_id") or "").strip()
        if not note_id:
            return ToolResult(output="", error="'note_id' is required for get_note")

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT note_id, project_id, created_at, source, title, body, tags "
                "FROM kb_notes WHERE note_id = ?",
                (note_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return ToolResult(output="", error=f"Note {note_id!r} not found")
        return ToolResult(output=json.dumps(dict(row), indent=2))

    def _list_notes(self, kw: dict) -> ToolResult:
        project_id = kw.get("project_id") or None
        tags_filter = (kw.get("tags") or "").strip()

        sql = (
            "SELECT note_id, project_id, created_at, title, tags, source "
            "FROM kb_notes"
        )
        params: list = []
        conditions: list[str] = []

        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        if tags_filter:
            conditions.append("tags LIKE ?")
            params.append(f"%{tags_filter}%")

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " LIMIT 50"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

        notes = [dict(r) for r in rows]
        return ToolResult(
            output=json.dumps({"count": len(notes), "notes": notes}, indent=2)
        )

    def _delete_note(self, kw: dict) -> ToolResult:
        note_id = (kw.get("note_id") or "").strip()
        if not note_id:
            return ToolResult(output="", error="'note_id' is required for delete_note")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM kb_notes WHERE note_id = ?", (note_id,))
            conn.commit()
        return ToolResult(output=json.dumps({"deleted": note_id}))
