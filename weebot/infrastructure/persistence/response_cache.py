"""File-based response cache with TTL and thread-safe atomic writes.

Extracted from deprecated weebot/ai_router.py.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional


class ResponseCache:
    """Simple file-based cache for LLM responses with TTL."""

    def __init__(self, cache_dir: Path, ttl_hours: int = 24) -> None:
        self.cache_dir = cache_dir
        self.ttl_hours = ttl_hours
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        cache_file = self.cache_dir / f"{key}.txt"
        with self._lock:
            if cache_file.exists():
                age = time.time() - cache_file.stat().st_mtime
                if age < (self.ttl_hours * 3600):
                    return cache_file.read_text(encoding="utf-8")
        return None

    def set(self, key: str, value: str) -> None:
        cache_file = self.cache_dir / f"{key}.txt"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            tmp_path: Optional[Path] = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.cache_dir,
                    prefix=f"{key}.",
                    suffix=".tmp",
                    delete=False,
                ) as tmp_file:
                    tmp_file.write(value)
                    tmp_path = Path(tmp_file.name)
                if tmp_path:
                    os.replace(tmp_path, cache_file)
            except Exception:
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()
                raise
