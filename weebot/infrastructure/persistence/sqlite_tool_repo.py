"""SQLite-backed ToolRepository — single adapter for all tool DB operations.

Consolidates previously separate sqlite3.connect() calls in:
  - knowledge_tool.py
  - product_tool.py
  - video_ingest_tool.py
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from weebot.application.ports.tool_repository_port import ToolRepositoryPort


class SQLiteToolRepository(ToolRepositoryPort):
    """Stores notes, video sources, and product requirements in a single DB."""

    def __init__(self, db_path: str = "./weebot_tools.db"):
        self._db_path = Path(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS kb_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS kb_notes_fts USING fts5(
                    title, content, tags, content='kb_notes', content_rowid='id'
                );
                CREATE TABLE IF NOT EXISTS video_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(url)
                );
                CREATE TABLE IF NOT EXISTS requirements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
        finally:
            conn.close()

    # ── Sync implementations (prefixed with _s_) called by async wrappers ──

    def _s_query_notes(self, search: str = "", limit: int = 20) -> list[dict]:
        conn = self._connect()
        try:
            if search:
                rows = conn.execute(
                    """SELECT kb_notes.* FROM kb_notes
                       JOIN kb_notes_fts ON kb_notes.id = kb_notes_fts.rowid
                       WHERE kb_notes_fts MATCH ?
                       ORDER BY kb_notes.created_at DESC LIMIT ?""",
                    (search, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM kb_notes ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _s_get_note(self, note_id: str) -> Optional[dict]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM kb_notes WHERE id = ?", (note_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def _s_list_notes(
        self, project_id: str = "", tags: Optional[list[str]] = None, limit: int = 50
    ) -> list[dict]:
        conn = self._connect()
        try:
            parts = ["SELECT * FROM kb_notes WHERE 1=1"]
            params: list[Any] = []
            if project_id:
                parts.append("AND project_id = ?")
                params.append(project_id)
            if tags:
                for tag in tags:
                    parts.append("AND tags LIKE ?")
                    params.append(f"%{tag}%")
            parts.append("ORDER BY created_at DESC LIMIT ?")
            params.append(limit)
            rows = conn.execute(" ".join(parts), params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _s_save_note(
        self, title: str, content: str, tags: Optional[list[str]] = None,
        project_id: str = "",
    ) -> str:
        tags_json = json.dumps(tags or [])
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO kb_notes (project_id, title, content, tags) VALUES (?, ?, ?, ?)",
                (project_id, title, content, tags_json),
            )
            note_id = str(cur.lastrowid)
            try:
                conn.execute(
                    "INSERT INTO kb_notes_fts (rowid, title, content, tags) VALUES (?, ?, ?, ?)",
                    (cur.lastrowid, title, content, tags_json),
                )
            except sqlite3.IntegrityError:
                pass
            conn.commit()
            return note_id
        finally:
            conn.close()

    def _s_delete_note(self, note_id: str) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM kb_notes WHERE id = ?", (note_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def _s_get_video_sources(self, project_id: str = "", limit: int = 50) -> list[dict]:
        conn = self._connect()
        try:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM video_sources WHERE project_id = ? ORDER BY ingested_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM video_sources ORDER BY ingested_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _s_save_video_source(
        self, url: str, title: str = "",
        project_id: str = "", metadata: Optional[dict] = None,
    ) -> str:
        meta_json = json.dumps(metadata or {})
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO video_sources (project_id, url, title, metadata)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                       title = excluded.title,
                       metadata = excluded.metadata""",
                (project_id, url, title, meta_json),
            )
            conn.commit()
            return str(cur.lastrowid or 0)
        finally:
            conn.close()

    def _s_get_requirements(
        self, project_id: str = "",
        status: Optional[str] = None, priority: Optional[str] = None,
    ) -> list[dict]:
        conn = self._connect()
        try:
            parts = ["SELECT * FROM requirements WHERE 1=1"]
            params: list[Any] = []
            if project_id:
                parts.append("AND project_id = ?")
                params.append(project_id)
            if status:
                parts.append("AND status = ?")
                params.append(status)
            if priority:
                parts.append("AND priority = ?")
                params.append(priority)
            parts.append("ORDER BY created_at DESC")
            rows = conn.execute(" ".join(parts), params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _s_save_requirement(
        self, title: str, description: str, priority: str = "medium",
        project_id: str = "",
    ) -> str:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO requirements (project_id, title, description, priority) VALUES (?, ?, ?, ?)",
                (project_id, title, description, priority),
            )
            conn.commit()
            return str(cur.lastrowid)
        finally:
            conn.close()

    def _s_update_requirement_status(self, req_id: str, new_status: str) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE requirements SET status = ? WHERE id = ?",
                (new_status, req_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # ── Async wrappers (public API matching ToolRepositoryPort) ──

    async def query_notes(self, search: str = "", limit: int = 20) -> list[dict]:
        return self._s_query_notes(search, limit)

    async def get_note(self, note_id: str) -> Optional[dict]:
        return self._s_get_note(note_id)

    async def list_notes(
        self, project_id: str = "", tags: Optional[list[str]] = None, limit: int = 50
    ) -> list[dict]:
        return self._s_list_notes(project_id, tags, limit)

    async def save_note(
        self, title: str, content: str, tags: Optional[list[str]] = None,
        project_id: str = "",
    ) -> str:
        return self._s_save_note(title, content, tags, project_id)

    async def delete_note(self, note_id: str) -> bool:
        return self._s_delete_note(note_id)

    async def get_video_sources(self, project_id: str = "", limit: int = 50) -> list[dict]:
        return self._s_get_video_sources(project_id, limit)

    async def save_video_source(
        self, url: str, title: str = "",
        project_id: str = "", metadata: Optional[dict] = None,
    ) -> str:
        return self._s_save_video_source(url, title, project_id, metadata)

    async def get_requirements(
        self, project_id: str = "",
        status: Optional[str] = None, priority: Optional[str] = None,
    ) -> list[dict]:
        return self._s_get_requirements(project_id, status, priority)

    async def save_requirement(
        self, title: str, description: str, priority: str = "medium",
        project_id: str = "",
    ) -> str:
        return self._s_save_requirement(title, description, priority, project_id)

    async def update_requirement_status(self, req_id: str, new_status: str) -> bool:
        return self._s_update_requirement_status(req_id, new_status)
