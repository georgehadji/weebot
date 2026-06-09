"""ToolResultCache — session-scoped in-memory cache for idempotent tool calls.

Key: sha256(tool_name + sorted JSON-serialized args).
Entries expire per-tool TTL. Non-cacheable tools bypass entirely.
Write-tracking invalidates read_file entries after a write to the same path.

Lives in the application layer with no infrastructure dependencies
(pure Python: dict + time).
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Optional

from weebot.tools.base import ToolResult

# Tools whose results are NEVER cached (side effects or non-deterministic).
NON_CACHEABLE_TOOLS: frozenset[str] = frozenset({
    "bash", "powershell", "run_shell",
    "write_file", "file_editor",
    "str_replace_editor",
    "advanced_browser", "browser_navigator", "browser_inspector",
    "computer_use", "screen_capture", "screenshot_ocr", "detect_elements",
    "terminate", "ask_human",
    "dispatch_agents", "subagent_rpc",
    "voice_input", "voice_output",
    "image_gen",
})

# Per-tool TTL overrides (seconds). Tools not listed use "_default".
DEFAULT_TTL_SECONDS: dict[str, int] = {
    "web_search": 300,       # 5 min
    "weather": 300,
    "weather_tool": 300,
    "knowledge": 3600,      # 1 hr
    "read_file": 60,         # 1 min
    "list_directory": 60,
    "search_files": 120,
    "search_content": 120,
    "glob": 120,
    "_default": 300,
}


@dataclass
class _CacheEntry:
    result: ToolResult
    expires_at: float


class ToolResultCache:
    """Session-scoped, in-memory LRU cache for idempotent tool results.

    Usage:
        cache = ToolResultCache()
        cached = cache.get("web_search", {"query": "..."})
        if cached is None:
            result = await tool.execute(...)
            cache.set("web_search", {"query": "..."}, result)
    """

    def __init__(self, max_entries: int = 500) -> None:
        self._store: dict[str, _CacheEntry] = {}
        self._written_paths: set[str] = set()
        self._max_entries = max_entries

    # ── Public API ─────────────────────────────────────────────────

    def get(self, tool_name: str, args: dict) -> Optional[ToolResult]:
        """Return cached result or None if not cached / expired / invalidated."""
        if tool_name in NON_CACHEABLE_TOOLS:
            return None

        # Invalidate read_file if the path was written to this session
        if tool_name in ("read_file", "list_directory"):
            path = args.get("path", "")
            if path in self._written_paths:
                return None

        key = self._make_key(tool_name, args)
        entry = self._store.get(key)
        if entry is None or time.monotonic() > entry.expires_at:
            return None
        return entry.result

    def set(self, tool_name: str, args: dict, result: ToolResult) -> None:
        """Store a result in the cache.

        Non-cacheable tools, errors, and write operations are not stored.
        Write operations are tracked for read-file invalidation.
        """
        # Track written paths for read_file invalidation (before non-cacheable
        # check, so even non-cacheable write tools invalidate read caches).
        if tool_name in ("write_file", "file_editor", "str_replace_editor"):
            path = args.get("path", "")
            if path:
                self._written_paths.add(path)
            return  # Don't cache write results

        if tool_name in NON_CACHEABLE_TOOLS or result.is_error:
            return

        ttl = DEFAULT_TTL_SECONDS.get(tool_name, DEFAULT_TTL_SECONDS["_default"])
        key = self._make_key(tool_name, args)

        # Evict oldest entry if at capacity
        if len(self._store) >= self._max_entries and key not in self._store:
            self._evict_one()

        self._store[key] = _CacheEntry(
            result=result,
            expires_at=time.monotonic() + ttl,
        )

    def invalidate(self, tool_name: str, args: dict) -> None:
        """Remove a specific entry from the cache."""
        key = self._make_key(tool_name, args)
        self._store.pop(key, None)

    def mark_path_written(self, path: str) -> None:
        """Register that *path* was written to, invalidating read caches."""
        if path:
            self._written_paths.add(path)

    def clear(self) -> None:
        """Clear all cached entries and write tracking."""
        self._store.clear()
        self._written_paths.clear()

    @property
    def size(self) -> int:
        return len(self._store)

    # ── Internal ───────────────────────────────────────────────────

    @staticmethod
    def _make_key(tool_name: str, args: dict) -> str:
        payload = tool_name + ":" + json.dumps(args, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _evict_one(self) -> None:
        """Remove a single expired or oldest entry."""
        now = time.monotonic()
        # Prefer evicting expired entries
        for key, entry in list(self._store.items()):
            if now > entry.expires_at:
                del self._store[key]
                return
        # If nothing expired, remove the first (oldest) entry
        if self._store:
            self._store.pop(next(iter(self._store)))
