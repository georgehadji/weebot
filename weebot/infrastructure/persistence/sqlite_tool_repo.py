"""SQLite-backed ToolRepository — single adapter for all tool DB operations.

Uses aiosqlite for non-blocking async I/O so that every database operation
yields to the asyncio event loop instead of blocking it.  Consolidates
previously separate sqlite3.connect() calls from:

  - knowledge_tool.py
  - product_tool.py
  - video_ingest_tool.py

Schema creation happens synchronously in ``__init__`` (one-time, low-cost)
using the stdlib ``sqlite3`` module so that no async bootstrap is required.
All runtime queries use ``aiosqlite``.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from weebot.application.ports.tool_repository_port import ToolRepositoryPort


class SQLiteToolRepository(ToolRepositoryPort):
    """Stores notes, video sources, and product requirements in a single DB.

    All public methods are ``async`` and use ``aiosqlite`` so that disk I/O
    never blocks the asyncio event loop.
    """

    def __init__(self, db_path: str = "./weebot_tools.db"):
        self._db_path = Path(db_path)
        self._init_schema()  # one-time, sync — acceptable at startup

    # ── Internal helpers ─────────────────────────────────────────────

    def _init_schema(self) -> None:
        """Create tables on first use (idempotent, sync — called once at init)."""
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
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

    async def _connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(str(self._db_path))
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Notes ────────────────────────────────────────────────────────

    async def query_notes(self, search: str = "", limit: int = 20) -> list[dict]:
        conn = await self._connect()
        try:
            if search:
                cursor = await conn.execute(
                    """SELECT kb_notes.* FROM kb_notes
                       JOIN kb_notes_fts ON kb_notes.id = kb_notes_fts.rowid
                       WHERE kb_notes_fts MATCH ?
                       ORDER BY kb_notes.created_at DESC LIMIT ?""",
                    (search, limit),
                )
                rows = await cursor.fetchall()
            else:
                cursor = await conn.execute(
                    "SELECT * FROM kb_notes ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
                rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def get_note(self, note_id: str) -> Optional[dict]:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "SELECT * FROM kb_notes WHERE id = ?", (note_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
        finally:
            await conn.close()

    async def list_notes(
        self, project_id: str = "", tags: Optional[list[str]] = None, limit: int = 50
    ) -> list[dict]:
        conn = await self._connect()
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
            cursor = await conn.execute(" ".join(parts), params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def save_note(
        self, title: str, content: str, tags: Optional[list[str]] = None,
        project_id: str = "",
    ) -> str:
        tags_json = json.dumps(tags or [])
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "INSERT INTO kb_notes (project_id, title, content, tags) VALUES (?, ?, ?, ?)",
                (project_id, title, content, tags_json),
            )
            note_id = str(cursor.lastrowid)
            try:
                await conn.execute(
                    "INSERT INTO kb_notes_fts (rowid, title, content, tags) VALUES (?, ?, ?, ?)",
                    (cursor.lastrowid, title, content, tags_json),
                )
            except aiosqlite.IntegrityError:
                pass
            await conn.commit()
            return note_id
        finally:
            await conn.close()

    async def delete_note(self, note_id: str) -> bool:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "DELETE FROM kb_notes WHERE id = ?", (note_id,)
            )
            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await conn.close()

    # ── Video sources ────────────────────────────────────────────────

    async def get_video_sources(self, project_id: str = "", limit: int = 50) -> list[dict]:
        conn = await self._connect()
        try:
            if project_id:
                cursor = await conn.execute(
                    "SELECT * FROM video_sources WHERE project_id = ? ORDER BY ingested_at DESC LIMIT ?",
                    (project_id, limit),
                )
            else:
                cursor = await conn.execute(
                    "SELECT * FROM video_sources ORDER BY ingested_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def save_video_source(
        self, url: str, title: str = "",
        project_id: str = "", metadata: Optional[dict] = None,
    ) -> str:
        meta_json = json.dumps(metadata or {})
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                """INSERT INTO video_sources (project_id, url, title, metadata)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                       title = excluded.title,
                       metadata = excluded.metadata""",
                (project_id, url, title, meta_json),
            )
            await conn.commit()
            return str(cursor.lastrowid or 0)
        finally:
            await conn.close()

    # ── Requirements ─────────────────────────────────────────────────

    async def get_requirements(
        self, project_id: str = "",
        status: Optional[str] = None, priority: Optional[str] = None,
    ) -> list[dict]:
        conn = await self._connect()
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
            cursor = await conn.execute(" ".join(parts), params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def save_requirement(
        self, title: str, description: str, priority: str = "medium",
        project_id: str = "",
    ) -> str:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "INSERT INTO requirements (project_id, title, description, priority) VALUES (?, ?, ?, ?)",
                (project_id, title, description, priority),
            )
            await conn.commit()
            return str(cursor.lastrowid)
        finally:
            await conn.close()

    async def update_requirement_status(self, req_id: str, new_status: str) -> bool:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                "UPDATE requirements SET status = ? WHERE id = ?",
                (new_status, req_id),
            )
            await conn.commit()
            return cursor.rowcount > 0
        finally:
            await conn.close()