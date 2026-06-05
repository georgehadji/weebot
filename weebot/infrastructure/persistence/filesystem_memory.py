"""FileSystemMemoryAdapter — MemoryPort implementation backed by flat .md files.

Stores in:
  ~/.weebot/memory/AGENT.md  — agent-accumulated knowledge and observations
  ~/.weebot/memory/USER.md   — user preferences, workflow habits, and profile
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import List, Optional

from weebot.application.ports.memory_port import MemoryPort

logger = logging.getLogger(__name__)

DELIMITER = "§"
import os as _os
DEFAULT_MEMORY_DIR = Path(
    _os.environ.get("WEEBOT_MEMORY_DIR", str(Path.home() / ".weebot" / "memory"))
)

# Prompt injection / exfiltration patterns — reject writes containing these.
_INJECTION_RE = re.compile(
    r"<INST>|</s>|SYSTEM:|<\|im_start\|>|<\|im_end\|>|\[INST\]|\[/INST\]|<\|system\|>",
    re.IGNORECASE,
)


class FileSystemMemoryAdapter(MemoryPort):
    """MemoryPort that reads/writes §-delimited entries in flat .md files."""

    def __init__(self, memory_dir: Optional[Path] = None) -> None:
        self._dir = memory_dir or DEFAULT_MEMORY_DIR

    # ── MemoryPort implementation ─────────────────────────────────────

    async def read_entries(self, file: str) -> List[str]:
        path = self._resolve(file)
        return await asyncio.to_thread(self._sync_load_entries, path)

    async def write_entries(self, file: str, entries: List[str]) -> None:
        path = self._resolve(file)
        await asyncio.to_thread(self._sync_save_entries, path, entries)

    async def read_snapshot(self) -> str:
        parts: list[str] = []
        for label, file in (("Agent Knowledge", "agent"), ("User Profile", "user")):
            path = self._resolve(file)
            if path.exists():
                text = await asyncio.to_thread(path.read_text, encoding="utf-8")
                text = text.strip()
                if text:
                    parts.append(f"## {label}\n{text}")
        if not parts:
            return ""
        return "# Persistent Memory\n\n" + "\n\n---\n\n".join(parts)

    # ── Sync helpers run via asyncio.to_thread ─────────────────────────

    def _resolve(self, file: str) -> Path:
        # Reject path separators and traversal sequences to prevent
        # writes escaping the memory directory (e.g. "../../../etc/passwd").
        if ".." in file or "/" in file or "\\" in file:
            raise ValueError(
                f"Invalid memory file name: {file!r}. "
                "Use alphanumeric names only (agent, user, etc.)."
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._dir / f"{file.upper()}.md"

    @staticmethod
    def _sync_load_entries(path: Path) -> List[str]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        return [e.strip() for e in text.split(DELIMITER) if e.strip()]

    @staticmethod
    def _sync_save_entries(path: Path, entries: List[str]) -> None:
        path.write_text(
            ("\n" + DELIMITER + "\n").join(entries),
            encoding="utf-8",
        )

    # ── Utilities ──────────────────────────────────────────────────────

    @staticmethod
    def scan_injection(text: str) -> bool:
        """Return True if *text* looks like a prompt injection attempt."""
        return bool(_INJECTION_RE.search(text))
