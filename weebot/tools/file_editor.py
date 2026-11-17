"""StrReplaceEditorTool — file view/create/str_replace/insert operations."""

from __future__ import annotations
from pathlib import Path
from typing import Any, ClassVar
from pydantic import PrivateAttr

from weebot.application.ports.syntax_check_port import SyntaxCheckPort
from weebot.application.services.file_state import FileStateRegistry
from weebot.application.services.patch_matching import STRATEGIES, Exact, apply_patch
from weebot.domain.models.output_trust import OutputTrust


from weebot.config.settings import WORKSPACE_ROOT
from weebot.tools.base import BaseTool, ToolResult
from weebot.infrastructure.security.security_validators import PathValidator, ValidationResult

# The canonical workspace root is in config.settings.WORKSPACE_ROOT.
# Tool-level overrides (e.g., for tests) use set_config(ToolConfig).


class StrReplaceEditorTool(BaseTool):

    output_trust: ClassVar[OutputTrust] = OutputTrust.EXTERNAL
    name: str = "file_editor"
    description: str = (
        "View, create, or edit files on the local filesystem. "
        "Commands: view (read file or list directory), create (write new file), "
        "str_replace (find-and-replace in file; small copying slips in old_str are tolerated "
        "and the result names the match), patch (several old_str/new_str hunks, all or none), "
        "insert (add lines at position). View a file before you edit it. "
        "All paths must be within the workspace."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["view", "create", "str_replace", "patch", "insert", "write_large"],
                "description": (
                    "Operation: 'view'=read, 'create'=write small file, "
                    "'str_replace'=find+replace, 'patch'=several find+replace hunks, "
                    "'insert'=add lines, "
                    "'write_large'=write large file via Python (preferred for >50 lines)"
                ),
            },
            "path": {
                "type": "string",
                "description": "Absolute or relative file/directory path (must be within workspace)",
            },
            "file_text": {
                "type": "string",
                "description": "Content to write (for 'create' command)",
            },
            "old_str": {"type": "string", "description": "Exact text to find (for 'str_replace')"},
            "new_str": {
                "type": "string",
                "description": "Replacement text (for 'str_replace' and 'insert')",
            },
            "exact": {
                "type": "boolean",
                "description": "For 'str_replace' and 'patch': match old_str exactly.",
            },
            "hunks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_str": {"type": "string"},
                        "new_str": {"type": "string"},
                    },
                    "required": ["old_str", "new_str"],
                },
                "description": "Edits for 'patch'; applied in order, all or none.",
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

    _file_state: FileStateRegistry | None = PrivateAttr(default=None)
    _syntax: SyntaxCheckPort | None = PrivateAttr(default=None)

    def __init__(
        self,
        file_state: FileStateRegistry | None = None,
        syntax: SyntaxCheckPort | None = None,
        **data,
    ):
        super().__init__(**data)
        # Unwired (no registry), the tool neither tracks views nor lints, as before H6.
        self._file_state = file_state
        self._syntax = syntax
        self._path_validator = PathValidator()
        self._workspace = Path(WORKSPACE_ROOT).resolve()

    @staticmethod
    def _fs_permissions():
        """Process-wide filesystem policy, loaded from config on first use.

        Resolved here rather than injected: this tool is built by a registry
        with no container access, and a DI binding with no reader is how the
        rest of this subsystem stayed dead for so long.
        """
        from weebot.application.services.fs_permission_policy import load_fs_permission_checker

        return load_fs_permission_checker()

    async def execute(self, command: str, path: str, **kwargs: Any) -> ToolResult:
        # ============================================================================
        # SECURITY: Validate path before any operation
        # ============================================================================

        # Check for null bytes (path injection)
        if "\x00" in path:
            return ToolResult(
                output="", error="Security error: Path contains invalid characters (null bytes)."
            )

        # Validate path is within workspace. A whole-file write (create, write_large) follows
        # the create rules whether or not the file exists: rewriting a script wholesale is
        # creating one (R13). str_replace and insert edit, so scripts stay editable.
        allow_create = command in ("create", "write_large")
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
                    "Use only simple relative paths within your workspace.",
                )
            elif validation_report.result == ValidationResult.INVALID_PATH:
                return ToolResult(
                    output="",
                    error=f"Access denied: Path must be within workspace: {self._workspace}",
                )
            elif validation_report.result == ValidationResult.DANGEROUS_PATTERN:
                return ToolResult(output="", error=f"Access denied: {validation_report.message}")
            else:
                return ToolResult(output="", error=f"Invalid path: {validation_report.message}")

        # Use the sanitized, resolved path
        safe_path = Path(validation_report.sanitized_value)

        # Double-check: ensure resolved path is still within workspace
        try:
            safe_path.relative_to(self._workspace)
        except ValueError:
            return ToolResult(
                output="", error="Access denied: Resolved path escapes workspace boundaries."
            )

        # ── Filesystem permission policy (audit 5.3) ─────────────────────
        # Layered on top of the workspace containment above, which decides
        # WHERE the agent may operate; this decides which subtrees inside the
        # workspace are off limits for this operation. safe_path is already
        # resolved, so a rule cannot be dodged with ".." or "./".
        _perm = self._fs_permissions()
        if _perm.has_rules:
            _operation = "read" if command == "view" else "write"
            _verdict = _perm.check(_operation, str(safe_path))
            if _verdict != "allow":
                # "interrupt" means "ask a human first". This tool has no
                # approval channel, and treating an unanswered gate as
                # permission would invert the rule's intent, so it fails
                # closed and reports why.
                import logging as _log

                _log.getLogger(__name__).warning(
                    "Filesystem policy %s: %s on %s", _verdict, _operation, safe_path
                )
                _detail = (
                    "requires human approval, which this tool cannot request"
                    if _verdict == "interrupt"
                    else "is denied by filesystem policy"
                )
                return ToolResult(
                    output="", error=f"Access denied: {_operation} on {safe_path} {_detail}."
                )

        # Execute the command with the safe path
        if command == "view":
            return self._view(safe_path, kwargs.get("view_range"))
        elif command == "create":
            return self._create(safe_path, kwargs.get("file_text", ""))
        elif command == "str_replace":
            return self._str_replace(
                safe_path,
                kwargs.get("old_str", ""),
                kwargs.get("new_str", ""),
                exact=bool(kwargs.get("exact")),
            )
        elif command == "patch":
            return self._patch(safe_path, kwargs.get("hunks"), exact=bool(kwargs.get("exact")))
        elif command == "insert":
            return self._insert(safe_path, kwargs.get("insert_line", 0), kwargs.get("new_str", ""))
        elif command == "write_large":
            return self._write_large(safe_path, kwargs.get("file_text", ""))
        return ToolResult(output="", error=f"Unknown command: {command!r}")

    def _write_large(self, path: Path, content: str) -> ToolResult:
        """Write a large file via Python to avoid context-overflow in file_editor."""

        if path.exists() and (stale := self._stale(path)):
            return stale
        # Write content to a temp file, then move it atomically
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
            size = path.stat().st_size
            lines = content.count("\n") + 1
            return self._written(
                path,
                content,
                ToolResult(
                    output=f"Wrote {path} ({lines} lines, {size} bytes)",
                    data={"path": str(path.resolve()), "lines": lines, "size_bytes": size},
                ),
            )
        except Exception as exc:
            return ToolResult(error=f"write_large failed: {exc}")

    def _stale(self, path: Path) -> ToolResult | None:
        """A refusal when the model has not seen the file as it now is (H6)."""
        reason = self._file_state.check(path) if self._file_state is not None else None
        return ToolResult(output="", error=f"Refused: {reason}.") if reason else None

    def _written(self, path: Path, text: str, result: ToolResult) -> ToolResult:
        """Note the file as written, and append any syntax problems; the write stands."""
        if self._file_state is not None:
            self._file_state.record(path)
        if self._syntax is not None:
            problems = self._syntax.check(str(path), text)
            if problems:
                result.output += "\nSyntax warning: " + "; ".join(problems)
        return result

    def _view(self, path: Path, view_range: list[int] | None) -> ToolResult:
        if path.is_dir():
            try:
                items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name))
                lines = [f"{'DIR ' if p.is_dir() else 'FILE'}  {p.name}" for p in items]
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
            return ToolResult(
                output="", error=f"Cannot read file (binary or unsupported encoding): {path}"
            )
        if self._file_state is not None:
            self._file_state.record(path)
        numbered = [f"{i + 1:4}: {line}" for i, line in enumerate(content.splitlines())]
        if view_range and len(view_range) == 2:
            start, end = view_range
            numbered = numbered[start - 1 : end]
        return ToolResult(output="\n".join(numbered))

    def _create(self, path: Path, text: str) -> ToolResult:
        # Additional safety: don't allow creating files outside workspace
        try:
            path.relative_to(self._workspace)
        except ValueError:
            return ToolResult(
                output="", error="Access denied: Cannot create files outside workspace"
            )

        # Check if file already exists
        if path.exists():
            return ToolResult(
                output="", error=f"File already exists: {path}. Use str_replace to modify."
            )

        # Check if any parent is an existing file (not a directory)
        for parent in reversed(path.parents):
            if parent == self._workspace:
                break
            if parent.exists() and not parent.is_dir():
                return ToolResult(
                    output="",
                    error=f"Cannot create file: Parent component {parent} exists but is a file, not a directory.",
                )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except PermissionError:
            return ToolResult(output="", error=f"Permission denied creating file: {path}")
        return self._written(path, text, ToolResult(output=f"Created {path} ({len(text)} chars)"))

    def _load_for_edit(self, path: Path) -> tuple[str, ToolResult | None]:
        """The file's text, or the refusal to report: missing, binary, unreadable or stale."""
        if not path.exists():
            return "", ToolResult(output="", error=f"File not found: {path}")
        if not path.is_file():
            return "", ToolResult(output="", error=f"Not a file: {path}")
        if stale := self._stale(path):
            return "", stale
        try:
            return path.read_text(encoding="utf-8"), None
        except PermissionError:
            return "", ToolResult(output="", error=f"Permission denied reading file: {path}")
        except UnicodeDecodeError:
            return "", ToolResult(output="", error=f"Cannot modify binary file: {path}")

    def _save_edit(self, path: Path, text: str, output: str) -> ToolResult:
        try:
            temp_path = path.with_suffix(path.suffix + ".tmp")
            temp_path.write_text(text, encoding="utf-8")
            temp_path.replace(path)  # Atomic on same filesystem
        except PermissionError:
            return ToolResult(output="", error=f"Permission denied writing file: {path}")
        return self._written(path, text, ToolResult(output=output))

    def _str_replace(
        self, path: Path, old_str: str, new_str: str, exact: bool = False
    ) -> ToolResult:
        if not old_str:
            # "" is in every string, so the new text was prepended and reported "Replaced".
            return ToolResult(output="", error="str_replace needs a non-empty old_str.")
        content, refusal = self._load_for_edit(path)
        if refusal:
            return refusal
        if exact:
            if old_str not in content:
                return ToolResult(output="", error=f"String not found in {path}: {old_str!r}")
            replaced = content.replace(old_str, new_str, 1)
            return self._save_edit(path, replaced, f"Replaced in {path}")
        outcome = apply_patch(content, old_str, new_str)
        if not outcome.ok:
            return ToolResult(output="", error=f"{path}: {outcome.error}")
        return self._save_edit(
            path, outcome.text, f"Replaced in {path} (line {outcome.line}, {outcome.strategy})"
        )

    def _patch(self, path: Path, hunks: object, exact: bool = False) -> ToolResult:
        """Apply every hunk in order to the text in memory, then write once: all or none."""
        if not isinstance(hunks, list) or not hunks:
            return ToolResult(output="", error="patch needs a non-empty list of hunks.")
        content, refusal = self._load_for_edit(path)
        if refusal:
            return refusal
        strategies = (Exact(),) if exact else STRATEGIES
        used = []
        for number, hunk in enumerate(hunks, 1):
            old = hunk.get("old_str") if isinstance(hunk, dict) else None
            new = hunk.get("new_str") if isinstance(hunk, dict) else None
            if not isinstance(old, str) or not isinstance(new, str):
                return ToolResult(output="", error=f"Hunk {number} needs old_str and new_str.")
            outcome = apply_patch(content, old, new, strategies=strategies)
            if not outcome.ok:
                return ToolResult(
                    output="", error=f"Hunk {number} failed, nothing was written: {outcome.error}"
                )
            content = outcome.text
            used.append(f"{number}: line {outcome.line}, {outcome.strategy}")
        return self._save_edit(
            path, content, f"Patched {path}: {len(hunks)} hunk(s) ({'; '.join(used)})"
        )

    def _insert(self, path: Path, insert_line: int, new_str: str) -> ToolResult:
        content, refusal = self._load_for_edit(path)
        if refusal:
            return refusal
        lines = content.splitlines(keepends=True)
        new_lines = new_str.splitlines(keepends=True)
        new_lines = [ln if ln.endswith("\n") else ln + "\n" for ln in new_lines]
        lines[insert_line:insert_line] = new_lines
        return self._save_edit(
            path,
            "".join(lines),
            f"Inserted {len(new_lines)} line(s) at position {insert_line} in {path}",
        )
