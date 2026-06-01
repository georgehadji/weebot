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
import re
from pathlib import Path
from typing import Any, Literal, Optional

from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

__all__ = ["PersistentMemoryTool"]

DELIMITER = "§"
MEMORY_DIR = Path.home() / ".weebot" / "memory"

# Prompt injection / exfiltration patterns — reject writes containing these.
# Memory entries are injected verbatim into the system prompt, so a poisoned
# entry would persist across sessions until explicitly removed.
_INJECTION_RE = re.compile(
    r"<INST>|</s>|SYSTEM:|<\|im_start\|>|<\|im_end\|>|\[INST\]|\[/INST\]|<\|system\|>",
    re.IGNORECASE,
)


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

    async def execute(
        self,
        action: Literal["add", "replace", "remove", "read"],
        file: Literal["agent", "user"] = "agent",
        entry: Optional[str] = None,
        match: Optional[str] = None,
        **_: Any,
    ) -> ToolResult:
        path = self._memory_path(file)

        if action == "read":
            return self._read(path)
        if action == "add":
            if not entry:
                return ToolResult.error_result("'entry' is required for action='add'")
            return self._add(path, entry)
        if action == "replace":
            if not entry or not match:
                return ToolResult.error_result("'entry' and 'match' are required for action='replace'")
            return self._replace(path, match, entry)
        if action == "remove":
            if not match:
                return ToolResult.error_result("'match' is required for action='remove'")
            return self._remove(path, match)
        return ToolResult.error_result(f"Unknown action: {action!r}")

    # ── path helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _memory_path(file: str) -> Path:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        return MEMORY_DIR / f"{file.upper()}.md"

    @staticmethod
    def _load_entries(path: Path) -> list[str]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        return [e.strip() for e in text.split(DELIMITER) if e.strip()]

    @staticmethod
    def _save_entries(path: Path, entries: list[str]) -> None:
        path.write_text(
            ("\n" + DELIMITER + "\n").join(entries),
            encoding="utf-8",
        )

    @staticmethod
    def _scan_injection(text: str) -> bool:
        """Return True if the text looks like a prompt injection attempt."""
        return bool(_INJECTION_RE.search(text))

    # ── actions ───────────────────────────────────────────────────────────

    def _read(self, path: Path) -> ToolResult:
        entries = self._load_entries(path)
        if not entries:
            return ToolResult.success_result(
                output="(no entries)", data={"entries": [], "count": 0}
            )
        formatted = "\n\n".join(f"[{i + 1}] {e}" for i, e in enumerate(entries))
        return ToolResult.success_result(
            output=formatted,
            data={"entries": entries, "count": len(entries)},
        )

    def _add(self, path: Path, entry: str) -> ToolResult:
        if self._scan_injection(entry):
            return ToolResult.error_result(
                "Entry rejected: contains a potential prompt injection pattern."
            )
        entries = self._load_entries(path)
        entries.append(entry)
        self._save_entries(path, entries)
        return ToolResult.success_result(
            output=f"Added entry #{len(entries)} to {path.name}.",
            data={"count": len(entries)},
        )

    def _replace(self, path: Path, match: str, new_entry: str) -> ToolResult:
        if self._scan_injection(new_entry):
            return ToolResult.error_result(
                "Entry rejected: contains a potential prompt injection pattern."
            )
        entries = self._load_entries(path)
        replaced = 0
        for i, e in enumerate(entries):
            if match in e:
                entries[i] = new_entry
                replaced += 1
        if not replaced:
            return ToolResult.error_result(f"No entries matched '{match}'")
        self._save_entries(path, entries)
        return ToolResult.success_result(
            output=f"Replaced {replaced} entry/entries in {path.name}.",
            data={"replaced": replaced},
        )

    def _remove(self, path: Path, match: str) -> ToolResult:
        entries = self._load_entries(path)
        before = len(entries)
        entries = [e for e in entries if match not in e]
        removed = before - len(entries)
        if not removed:
            return ToolResult.error_result(f"No entries matched '{match}'")
        self._save_entries(path, entries)
        return ToolResult.success_result(
            output=f"Removed {removed} entry/entries from {path.name}.",
            data={"removed": removed},
        )

    # ── system prompt snapshot ────────────────────────────────────────────

    @classmethod
    def load_snapshot(cls) -> str:
        """Return a formatted snapshot of both memory files for system prompt injection.

        Returns empty string if both files are empty or missing.
        This method is called once at session start to build a frozen snapshot
        that is prepended to the system prompt. Mid-session writes update disk
        but do NOT change the returned snapshot — this preserves the prefix cache.
        """
        parts: list[str] = []
        for label, file in (("Agent Knowledge", "agent"), ("User Profile", "user")):
            path = MEMORY_DIR / f"{file.upper()}.md"
            if path.exists():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    parts.append(f"## {label}\n{text}")
        if not parts:
            return ""
        return "# Persistent Memory\n\n" + "\n\n---\n\n".join(parts)
