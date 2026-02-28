"""StrReplaceEditorTool — file view/create/str_replace/insert operations."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from weebot.tools.base import BaseTool, ToolResult


class StrReplaceEditorTool(BaseTool):
    name: str = "file_editor"
    description: str = (
        "View, create, or edit files on the local filesystem. "
        "Commands: view (read file or list directory), create (write new file), "
        "str_replace (find-and-replace in file), insert (add lines at position)."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["view", "create", "str_replace", "insert"],
                "description": "Operation to perform",
            },
            "path": {
                "type": "string",
                "description": "Absolute or relative file/directory path",
            },
            "file_text": {
                "type": "string",
                "description": "Content to write (for 'create' command)",
            },
            "old_str": {
                "type": "string",
                "description": "Exact text to find (for 'str_replace')",
            },
            "new_str": {
                "type": "string",
                "description": "Replacement text (for 'str_replace' and 'insert')",
            },
            "insert_line": {
                "type": "integer",
                "description": (
                    "Line number after which to insert new content (0 = before line 1) "
                    "for 'insert' command"
                ),
            },
            "view_range": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "[start_line, end_line] for partial 'view' (1-based)",
            },
        },
        "required": ["command", "path"],
    }

    async def execute(self, command: str, path: str, **kwargs: Any) -> ToolResult:
        p = Path(path)
        if command == "view":
            return self._view(p, kwargs.get("view_range"))
        elif command == "create":
            return self._create(p, kwargs.get("file_text", ""))
        elif command == "str_replace":
            return self._str_replace(
                p, kwargs.get("old_str", ""), kwargs.get("new_str", "")
            )
        elif command == "insert":
            return self._insert(
                p, kwargs.get("insert_line", 0), kwargs.get("new_str", "")
            )
        return ToolResult(output="", error=f"Unknown command: {command!r}")

    def _view(self, path: Path, view_range: list[int] | None) -> ToolResult:
        if path.is_dir():
            items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name))
            lines = [
                f"{'DIR ' if p.is_dir() else 'FILE'}  {p.name}" for p in items
            ]
            return ToolResult(output="\n".join(lines) or "(empty directory)")
        if not path.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        numbered = [
            f"{i + 1:4}: {line}" for i, line in enumerate(content.splitlines())
        ]
        if view_range and len(view_range) == 2:
            start, end = view_range
            numbered = numbered[start - 1: end]
        return ToolResult(output="\n".join(numbered))

    def _create(self, path: Path, text: str) -> ToolResult:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return ToolResult(output=f"Created {path} ({len(text)} chars)")

    def _str_replace(self, path: Path, old_str: str, new_str: str) -> ToolResult:
        if not path.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        content = path.read_text(encoding="utf-8")
        if old_str not in content:
            return ToolResult(
                output="", error=f"String not found in {path}: {old_str!r}"
            )
        new_content = content.replace(old_str, new_str, 1)
        path.write_text(new_content, encoding="utf-8")
        return ToolResult(output=f"Replaced in {path}")

    def _insert(self, path: Path, insert_line: int, new_str: str) -> ToolResult:
        if not path.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines = new_str.splitlines(keepends=True)
        new_lines = [ln if ln.endswith("\n") else ln + "\n" for ln in new_lines]
        lines[insert_line:insert_line] = new_lines
        path.write_text("".join(lines), encoding="utf-8")
        return ToolResult(
            output=f"Inserted {len(new_lines)} line(s) at position {insert_line} in {path}"
        )
