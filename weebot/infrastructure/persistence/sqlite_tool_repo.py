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
from typing import Any

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
                    url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(url)
                );
                CREATE TABLE IF NOT EXISTS requirements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    # ---- Notes ----

    def query_notes(self, search: str = "", limit: int = 20) -> list[dict]:
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

    def save_note(
        self, title: str, content: str, tags: list[str] | None = None
    ) -> str:
        tags_json = json.dumps(tags or [])
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO kb_notes (title, content, tags) VALUES (?, ?, ?)",
                (title, content, tags_json),
            )
            note_id = str(cur.lastrowid)
            # Sync FTS index
            try:
                conn.execute(
                    "INSERT INTO kb_notes_fts (rowid, title, content, tags) VALUES (?, ?, ?, ?)",
                    (cur.lastrowid, title, content, tags_json),
                )
            except sqlite3.IntegrityError:
                pass  # FTS trigger may auto-sync
            conn.commit()
            return note_id
        finally:
            conn.close()

    def delete_note(self, note_id: str) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM kb_notes WHERE id = ?", (note_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # ---- Video sources ----

    def get_video_sources(self, limit: int = 50) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM video_sources ORDER BY ingested_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def save_video_source(
        self, url: str, title: str = "", metadata: dict | None = None
    ) -> str:
        meta_json = json.dumps(metadata or {})
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO video_sources (url, title, metadata)
                   VALUES (?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                       title = excluded.title,
                       metadata = excluded.metadata""",
                (url, title, meta_json),
            )
            conn.commit()
            return str(cur.lastrowid or 0)
        finally:
            conn.close()

    # ---- Requirements ----

    def get_requirements(self, status: str | None = None) -> list[dict]:
        conn = self._connect()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM requirements WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM requirements ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def save_requirement(
        self, title: str, description: str, priority: str = "medium"
    ) -> str:
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO requirements (title, description, priority) VALUES (?, ?, ?)",
                (title, description, priority),
            )
            conn.commit()
            return str(cur.lastrowid)
        finally:
            conn.close()

    # ---- Async wrappers (for async tools) ----

    async def query_notes(self, search: str = "", limit: int = 20) -> list[dict]:
        return self.query_notes(search, limit)

    async def save_note(
        self, title: str, content: str, tags: list[str] | None = None
    ) -> str:
        return self.save_note(title, content, tags)

    async def delete_note(self, note_id: str) -> bool:
        return self.delete_note(note_id)

    async def get_video_sources(self, limit: int = 50) -> list[dict]:
        return self.get_video_sources(limit)

    async def save_video_source(
        self, url: str, title: str = "", metadata: dict | None = None
    ) -> str:
        return self.save_video_source(url, title, metadata)

    async def get_requirements(self, status: str | None = None) -> list[dict]:
        return self.get_requirements(status)

    async def save_requirement(
        self, title: str, description: str, priority: str = "medium"
    ) -> str:
        return self.save_requirement(title, description, priority)
