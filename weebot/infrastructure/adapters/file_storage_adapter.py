"""LocalFileStorageAdapter — local-filesystem implementation of FileStoragePort.

Wraps aiofiles for async I/O with automatic parent-directory creation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import aiofiles
import yaml

from weebot.application.ports.file_storage_port import FileStoragePort


class LocalFileStorageAdapter(FileStoragePort):
    """Reads and writes files on the local filesystem using aiofiles.

    All paths are resolved relative to *root_dir* (default: current directory).
    This prevents path-traversal issues and makes the adapter testable with a
    temporary directory.
    """

    def __init__(self, root_dir: str | Path = ".") -> None:
        self._root = Path(root_dir).resolve()

    def _resolve(self, path: str) -> Path:
        """Resolve *path* relative to root_dir, rejecting traversal attempts."""
        full = (self._root / path).resolve()
        if not str(full).startswith(str(self._root)):
            raise ValueError(f"Path traversal blocked: {path}")
        return full

    async def read_text(self, path: str) -> str:
        full = self._resolve(path)
        async with aiofiles.open(full, "r", encoding="utf-8") as f:
            return await f.read()

    async def write_text(self, path: str, content: str) -> None:
        full = self._resolve(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(full, "w", encoding="utf-8") as f:
            await f.write(content)

    async def read_yaml(self, path: str) -> dict[str, Any]:
        try:
            text = await self.read_text(path)
            data = yaml.safe_load(text)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}

    async def write_yaml(self, path: str, data: dict[str, Any]) -> None:
        content = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
        await self.write_text(path, content)

    async def read_json(self, path: str) -> Any:
        text = await self.read_text(path)
        return json.loads(text)

    async def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    async def delete(self, path: str) -> bool:
        full = self._resolve(path)
        if full.exists():
            full.unlink()
            return True
        return False
