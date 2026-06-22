"""PersistentMemoryTool — file-backed §-delimited cross-session memory store.

Inspired by hermes-agent's memory_tool pattern. Stores in two files:
  ~/.weebot/memory/AGENT.md  — agent-accumulated knowledge and observations
  ~/.weebot/memory/USER.md   — user preferences, workflow habits, and profile

Both files are injected into the system prompt as a FROZEN snapshot at session
start (via PersistentMemoryTool.load_snapshot()). This preserves the LLM's
prefix cache for the entire session — mid-session writes update disk immediately
but the snapshot only refreshes when the next session starts.

Entry delimiter: § (section sign, rare in natural text).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, Optional

from weebot.application.ports.memory_port import MemoryPort
from weebot.infrastructure.persistence.filesystem_memory import (
    FileSystemMemoryAdapter,
    DELIMITER,
)
from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

__all__ = ["PersistentMemoryTool"]


class PersistentMemoryTool(BaseTool):
    """Read and write persistent cross-session memory files.

    Actions:
        add     — append a new §-delimited entry to the file
        replace — replace an existing entry (matched by substring)
        remove  — delete matching entries (matched by substring)
        read    — return all entries in the file

    Files:
        agent — ~/.weebot/memory/AGENT.md (agent knowledge)
        user  — ~/.weebot/memory/USER.md  (user profile/preferences)
    """

    name: str = "persistent_memory"
    description: str = (
        "Read and write persistent memory that survives across sessions. "
        "Use 'agent' file for accumulated facts and observations; "
        "'user' file for user preferences and workflow habits. "
        "Actions: add, replace, remove, read."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove", "read"],
                "description": "Operation to perform on the memory file.",
            },
            "file": {
                "type": "string",
                "enum": ["agent", "user"],
                "description": "Which memory file to target (default: agent).",
                "default": "agent",
            },
            "entry": {
                "type": "string",
                "description": "Entry content to add or the replacement text (required for add/replace).",
            },
            "match": {
                "type": "string",
                "description": "Substring to find for replace/remove operations.",
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        memory: Optional[MemoryPort] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the persistent memory tool.

        Args:
            memory: A MemoryPort implementation injected by DI.
                When None (constructed by RoleBasedToolRegistry),
                uses the default adapter from the DI container.
            **kwargs: Passed through to BaseTool.
        """
        super().__init__(**kwargs)
        if memory is None:
            from weebot.application.di import Container
            container = Container()
            container.configure_defaults()
            memory = container.get(MemoryPort)
        self._memory = memory

    async def execute(
        self,
        action: Literal["add", "replace", "remove", "read"],
        file: Literal["agent", "user"] = "agent",
        entry: Optional[str] = None,
        match: Optional[str] = None,
        **_: Any,
    ) -> ToolResult:
        if action == "read":
            return await self._read(file)
        if action == "add":
            if not entry:
                return ToolResult.error_result("'entry' is required for action='add'")
            return await self._add(file, entry)
        if action == "replace":
            if not entry or not match:
                return ToolResult.error_result("'entry' and 'match' are required for action='replace'")
            return await self._replace(file, match, entry)
        if action == "remove":
            if not match:
                return ToolResult.error_result("'match' is required for action='remove'")
            return await self._remove(file, match)
        return ToolResult.error_result(f"Unknown action: {action!r}")

    # ── actions ───────────────────────────────────────────────────────────

    async def _track_salience(self, entry_text: str, source: str) -> None:
        """Record salience metadata for a memory entry (best-effort, non-fatal).

        Uses a lazily-initialised SQLiteStateRepository — the first call
        triggers connection pool creation, subsequent calls reuse it.
        """
        try:
            import hashlib
            from weebot.application.services.salience_scorer import compute_salience
            if not hasattr(self, '_salience_repo'):
                from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository
                self._salience_repo = SQLiteStateRepository()
            entry_hash = hashlib.sha256(entry_text.encode()).hexdigest()[:16]
            salience = compute_salience(access_count=2)
            await self._salience_repo.upsert_memory_metadata(
                entry_hash, entry_text[:500], source, salience,
            )
        except Exception:
            pass

    async def _read(self, file: str) -> ToolResult:
        entries = await self._memory.read_entries(file)
        for entry_text in entries:
            if entry_text.strip():
                await self._track_salience(entry_text, file)
        if not entries:
            return ToolResult.success_result(
                output="(no entries)", data={"entries": [], "count": 0}
            )
        formatted = "\n\n".join(f"[{i + 1}] {e}" for i, e in enumerate(entries))
        return ToolResult.success_result(
            output=formatted,
            data={"entries": entries, "count": len(entries)},
        )

    async def _add(self, file: str, entry: str) -> ToolResult:
        if FileSystemMemoryAdapter.scan_injection(entry):
            return ToolResult.error_result(
                "Entry rejected: contains a potential prompt injection pattern."
            )
        await self._track_salience(entry, file)
        entries = await self._memory.read_entries(file)
        entries.append(entry)
        await self._memory.write_entries(file, entries)
        return ToolResult.success_result(
            output=f"Added entry #{len(entries)} to {file.upper()}.md.",
            data={"count": len(entries)},
        )

    async def _replace(self, file: str, match: str, new_entry: str) -> ToolResult:
        if FileSystemMemoryAdapter.scan_injection(new_entry):
            return ToolResult.error_result(
                "Entry rejected: contains a potential prompt injection pattern."
            )
        entries = await self._memory.read_entries(file)
        replaced = 0
        for i, e in enumerate(entries):
            if match in e:
                entries[i] = new_entry
                replaced += 1
        if not replaced:
            return ToolResult.error_result(f"No entries matched '{match}'")
        await self._memory.write_entries(file, entries)
        return ToolResult.success_result(
            output=f"Replaced {replaced} entry/entries in {file.upper()}.md.",
            data={"replaced": replaced},
        )

    async def _remove(self, file: str, match: str) -> ToolResult:
        entries = await self._memory.read_entries(file)
        before = len(entries)
        entries = [e for e in entries if match not in e]
        removed = before - len(entries)
        if not removed:
            return ToolResult.error_result(f"No entries matched '{match}'")
        await self._memory.write_entries(file, entries)
        return ToolResult.success_result(
            output=f"Removed {removed} entry/entries from {file.upper()}.md.",
            data={"removed": removed},
        )

    # ── system prompt snapshot ────────────────────────────────────────────

    @classmethod
    async def load_snapshot(cls) -> str:
        """Return a formatted snapshot of both memory files for system prompt injection.

        Returns empty string if both files are empty or missing.
        This method is called once at session start to build a frozen snapshot
        that is prepended to the system prompt. Mid-session writes update disk
        but do NOT change the returned snapshot — this preserves the prefix cache.
        """
        adapter = FileSystemMemoryAdapter()
        return await adapter.read_snapshot()
