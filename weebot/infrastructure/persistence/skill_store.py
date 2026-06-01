"""Skill store — persists Skill models with version history.

Uses the same SQLite connection pool as the trajectory repository
for a single database.  Skill documents are stored as JSON in a
dedicated table alongside the existingsession/trajectory tables.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from weebot.domain.models.skill import Skill
from weebot.infrastructure.persistence.connection_pool import get_or_create_pool

logger = logging.getLogger(__name__)


class SkillStore:
    """Persistence for Skill models with full version history."""

    def __init__(self, db_path: str = "./weebot_sessions.db"):
        self._db_path = Path(db_path)
        self._pool = None
        self._initialized = False

    async def _get_pool(self):
        if self._pool is None:
            self._pool = await get_or_create_pool(
                self._db_path, max_read_connections=5, enable_wal=True
            )
            if not self._initialized:
                await self._ensure_schema()
                self._initialized = True
        return self._pool

    async def _ensure_schema(self):
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skills (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL DEFAULT '',
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            logger.debug("Skill table schema ensured")

    async def save(self, skill: Skill) -> None:
        """Persist a skill with full version history."""
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO skills (name, description, data_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    skill.name,
                    skill.description,
                    skill.model_dump_json(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            logger.debug("Skill '%s' saved (v%d)", skill.name, skill.current_version)

    async def load(self, name: str) -> Optional[Skill]:
        """Load a skill by name."""
        pool = await self._get_pool()
        row = await pool.execute_read(
            "SELECT data_json FROM skills WHERE name = ?",
            (name,),
            fetch_all=False,
        )
        if not row:
            return None
        try:
            return Skill.model_validate_json(row["data_json"])
        except Exception as exc:
            logger.error("Failed to deserialize skill '%s': %s", name, exc)
            return None

    async def list_names(self) -> list[str]:
        """Return all stored skill names."""
        pool = await self._get_pool()
        rows = await pool.execute_read(
            "SELECT name FROM skills ORDER BY name"
        )
        return [r["name"] for r in rows]

    async def delete(self, name: str) -> bool:
        """Delete a skill.  Returns True if it existed."""
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            cursor = await conn.execute(
                "DELETE FROM skills WHERE name = ?", (name,)
            )
            await cursor.close()
            # Check if existed by trying to load
            existing = await self.load(name)
            return existing is None

    async def export_best_md(self, name: str, output_path: str) -> None:
        """Write the best-validated skill content to a markdown file."""
        skill = await self.load(name)
        if skill is None:
            raise FileNotFoundError(f"Skill '{name}' not found")
        content = skill.export_best()
        path = Path(output_path)
        path.write_text(content, encoding="utf-8")
        logger.info("Exported best skill '%s' to %s", name, output_path)

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
