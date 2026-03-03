"""StrReplaceEditorTool — file view/create/str_replace/insert operations."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from weebot.tools.base import BaseTool, ToolResult
from weebot.security_validators import PathValidator, InputSanitizer, ValidationResult
from weebot.config.settings import WORKSPACE_ROOT


class StrReplaceEditorTool(BaseTool):
    name: str = "file_editor"
    description: str = (
        "View, create, or edit files on the local filesystem. "
        "Commands: view (read file or list directory), create (write new file), "
        "str_replace (find-and-replace in file), insert (add lines at position). "
        "All paths must be within the workspace."
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
                "description": "Absolute or relative file/directory path (must be within workspace)",
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

    def __init__(self, **data):
        super().__init__(**data)
        self._path_validator = PathValidator()
        self._workspace = WORKSPACE_ROOT.resolve()

    async def execute(self, command: str, path: str, **kwargs: Any) -> ToolResult:
        # ============================================================================
        # SECURITY: Validate path before any operation
        # ============================================================================
        
        # Check for null bytes (path injection)
        if "\x00" in path:
            return ToolResult(
                output="",
                error="Security error: Path contains invalid characters (null bytes)."
            )
        
        # Validate path is within workspace
        allow_create = (command == "create")
        validation_report = self._path_validator.validate(path, allow_create=allow_create)
        
        if validation_report.result != ValidationResult.VALID:
            # Log the security event
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Path validation blocked: {validation_report.message} "
                f"[pattern={validation_report.matched_pattern}]"
            )
            
            # Return user-friendly error based on the type of violation
            if validation_report.result == ValidationResult.INJECTION_DETECTED:
                return ToolResult(
                    output="",
                    error="Access denied: Path contains potentially dangerous patterns. "
                          "Use only simple relative paths within your workspace."
                )
            elif validation_report.result == ValidationResult.INVALID_PATH:
                return ToolResult(
                    output="",
                    error=f"Access denied: Path must be within workspace: {self._workspace}"
                )
            elif validation_report.result == ValidationResult.DANGEROUS_PATTERN:
                return ToolResult(
                    output="",
                    error=f"Access denied: {validation_report.message}"
                )
            else:
                return ToolResult(
                    output="",
                    error=f"Invalid path: {validation_report.message}"
                )
        
        # Use the sanitized, resolved path
        safe_path = Path(validation_report.sanitized_value)
        
        # Double-check: ensure resolved path is still within workspace
        try:
            safe_path.relative_to(self._workspace)
        except ValueError:
            return ToolResult(
                output="",
                error=f"Access denied: Resolved path escapes workspace boundaries."
            )
        
        # Execute the command with the safe path
        if command == "view":
            return self._view(safe_path, kwargs.get("view_range"))
        elif command == "create":
            return self._create(safe_path, kwargs.get("file_text", ""))
        elif command == "str_replace":
            return self._str_replace(
                safe_path, kwargs.get("old_str", ""), kwargs.get("new_str", "")
            )
        elif command == "insert":
            return self._insert(
                safe_path, kwargs.get("insert_line", 0), kwargs.get("new_str", "")
            )
        return ToolResult(output="", error=f"Unknown command: {command!r}")

    def _view(self, path: Path, view_range: list[int] | None) -> ToolResult:
        if path.is_dir():
            try:
                items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name))
                lines = [
                    f"{'DIR ' if p.is_dir() else 'FILE'}  {p.name}" for p in items
                ]
                return ToolResult(output="\n".join(lines) or "(empty directory)")
            except PermissionError:
                return ToolResult(output="", error=f"Permission denied accessing directory: {path}")
        if not path.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return ToolResult(output="", error=f"Permission denied reading file: {path}")
        except UnicodeDecodeError:
            return ToolResult(output="", error=f"Cannot read file (binary or unsupported encoding): {path}")
        numbered = [
            f"{i + 1:4}: {line}" for i, line in enumerate(content.splitlines())
        ]
        if view_range and len(view_range) == 2:
            start, end = view_range
            numbered = numbered[start - 1: end]
        return ToolResult(output="\n".join(numbered))

    def _create(self, path: Path, text: str) -> ToolResult:
        # Additional safety: don't allow creating files outside workspace
        try:
            path.relative_to(self._workspace)
        except ValueError:
            return ToolResult(output="", error="Access denied: Cannot create files outside workspace")
        
        # Check if file already exists
        if path.exists():
            return ToolResult(output="", error=f"File already exists: {path}. Use str_replace to modify.")
        
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except PermissionError:
            return ToolResult(output="", error=f"Permission denied creating file: {path}")
        return ToolResult(output=f"Created {path} ({len(text)} chars)")

    def _str_replace(self, path: Path, old_str: str, new_str: str) -> ToolResult:
        if not path.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        if not path.is_file():
            return ToolResult(output="", error=f"Not a file: {path}")
        try:
            content = path.read_text(encoding="utf-8")
        except PermissionError:
            return ToolResult(output="", error=f"Permission denied reading file: {path}")
        except UnicodeDecodeError:
            return ToolResult(output="", error=f"Cannot modify binary file: {path}")
        if old_str not in content:
            return ToolResult(
                output="", error=f"String not found in {path}: {old_str!r}"
            )
        new_content = content.replace(old_str, new_str, 1)
        try:
            path.write_text(new_content, encoding="utf-8")
        except PermissionError:
            return ToolResult(output="", error=f"Permission denied writing file: {path}")
        return ToolResult(output=f"Replaced in {path}")

    def _insert(self, path: Path, insert_line: int, new_str: str) -> ToolResult:
        if not path.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        if not path.is_file():
            return ToolResult(output="", error=f"Not a file: {path}")
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except PermissionError:
            return ToolResult(output="", error=f"Permission denied reading file: {path}")
        except UnicodeDecodeError:
            return ToolResult(output="", error=f"Cannot modify binary file: {path}")
        new_lines = new_str.splitlines(keepends=True)
        new_lines = [ln if ln.endswith("\n") else ln + "\n" for ln in new_lines]
        lines[insert_line:insert_line] = new_lines
        try:
            path.write_text("".join(lines), encoding="utf-8")
        except PermissionError:
            return ToolResult(output="", error=f"Permission denied writing file: {path}")
        return ToolResult(
            output=f"Inserted {len(new_lines)} line(s) at position {insert_line} in {path}"
        )
