"""File-backed spillover store: ``<base>/<session>/<call>.txt`` (H7).

The files are written by the system, not by ``file_editor`` for the session, so they are
deliberately not in the session's written-file set: reading one back taints the session
exactly as the original output would have (decision D5).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
from pathlib import Path

from weebot.application.ports.spillover_store_port import SpilloverStorePort, SpillRef

DEFAULT_SPILLOVER_DIR = Path.home() / ".weebot" / "spillover"


def _safe(name: str) -> str:
    """A path-safe form of an id; distinct ids stay distinct."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]|\.\.", "_", name).strip(".") or "x"
    if cleaned == name:
        return cleaned
    return f"{cleaned}-{hashlib.sha1(name.encode()).hexdigest()[:8]}"


class FileSpilloverStore(SpilloverStorePort):
    def __init__(self, base_dir: Path = DEFAULT_SPILLOVER_DIR) -> None:
        self._base = Path(base_dir)

    def _write(self, session_id: str, call_id: str, text: str) -> SpillRef:
        folder = self._base / _safe(session_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{_safe(call_id)}.txt"
        path.write_text(text, encoding="utf-8")
        return SpillRef(path=str(path), chars=len(text))

    def _purge(self, session_id: str) -> int:
        folder = self._base / _safe(session_id)
        if not folder.is_dir():
            return 0
        count = sum(1 for p in folder.iterdir() if p.is_file())
        shutil.rmtree(folder, ignore_errors=True)
        return count

    async def write(self, session_id: str, call_id: str, text: str) -> SpillRef:
        return await asyncio.to_thread(self._write, session_id, call_id, text)

    async def purge(self, session_id: str) -> int:
        return await asyncio.to_thread(self._purge, session_id)
