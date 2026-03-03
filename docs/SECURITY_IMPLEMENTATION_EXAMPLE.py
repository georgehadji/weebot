"""
Παράδειγμα πλήρους ενσωμάτωσης των security και error handling features
στο υπάρχον file_editor.py
"""

# =============================================================================
# BEFORE: Original vulnerable implementation
# =============================================================================

class StrReplaceEditorToolOLD(BaseTool):
    """Original version - VULNERABLE to path traversal"""
    
    async def execute(self, command: str, path: str, **kwargs) -> ToolResult:
        p = Path(path)  # NO VALIDATION!
        if command == "view":
            return self._view(p, kwargs.get("view_range"))
        # ...


# =============================================================================
# AFTER: Secure implementation with full error handling
# =============================================================================

from pathlib import Path
from typing import Any, Optional

from weebot.tools.base import BaseTool, ToolResult
from weebot.security_validators import PathValidator, InputSanitizer, ValidationResult
from weebot.error_system_base import WeebotError, ErrorCode, ErrorSeverity
from weebot.error_system_handler import handle_errors, ErrorHandler
from weebot.error_system_user_messages import get_user_message
from weebot.structured_logger import get_logger, LogContext


class StrReplaceEditorTool(BaseTool):
    """
    Secure file editor with path validation and comprehensive error handling.
    """
    
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
                "description": "Absolute or relative file/directory path (must be within workspace)",
            },
            # ... rest of parameters
        },
        "required": ["command", "path"],
    }
    
    def __init__(self):
        super().__init__()
        self._path_validator = PathValidator()
        self._logger = get_logger("weebot.tools.file_editor")
        self._error_handler = ErrorHandler()
    
    async def execute(self, command: str, path: str, **kwargs: Any) -> ToolResult:
        """
        Execute file operation with full security validation and error handling.
        """
        # Create correlation ID for this operation
        correlation_id = f"fe_{id(self)}_{command}"
        
        with LogContext(
            tool="file_editor",
            command=command,
            correlation_id=correlation_id
        ):
            self._logger.info(f"Starting file operation: {command}")
            
            try:
                # =========================================================================
                # STEP 1: Validate and sanitize the path
                # =========================================================================
                
                # Sanitize input for logging (prevent log injection)
                safe_path_for_log = InputSanitizer.sanitize_for_logs(path[:100])
                self._logger.debug(f"Validating path: {safe_path_for_log}")
                
                # Validate path security
                validation_report = self._path_validator.validate(
                    path, 
                    allow_create=(command == "create")
                )
                
                if validation_report.result != ValidationResult.VALID:
                    # Log security event
                    self._logger.warning(
                        f"Path validation failed: {validation_report.message}",
                        extra={
                            "attempted_path": safe_path_for_log,
                            "reason": validation_report.result.name,
                            "matched_pattern": validation_report.matched_pattern
                        }
                    )
                    
                    # Return user-friendly error
                    if validation_report.result == ValidationResult.INJECTION_DETECTED:
                        return ToolResult(
                            output="",
                            error=(
                                "Security alert: The specified path contains "
                                "potentially dangerous patterns. "
                                f"Please use a path within your workspace. "
                                f"[Reference: {correlation_id}]"
                            )
                        )
                    elif validation_report.result == ValidationResult.INVALID_PATH:
                        return ToolResult(
                            output="",
                            error=(
                                "Invalid path: The specified location is outside "
                                "the allowed workspace. Please use a relative path "
                                f"within your project directory. [Reference: {correlation_id}]"
                            )
                        )
                    else:
                        return ToolResult(
                            output="",
                            error=f"Path validation failed: {validation_report.message}"
                        )
                
                # Get the sanitized, resolved path
                safe_path = Path(validation_report.sanitized_value)
                self._logger.info(f"Path validated: {safe_path}")
                
                # =========================================================================
                # STEP 2: Execute the command
                # =========================================================================
                
                if command == "view":
                    result = self._view(safe_path, kwargs.get("view_range"))
                elif command == "create":
                    # Sanitize file content
                    file_text = kwargs.get("file_text", "")
                    result = self._create(safe_path, file_text)
                elif command == "str_replace":
                    old_str = kwargs.get("old_str", "")
                    new_str = kwargs.get("new_str", "")
                    result = self._str_replace(safe_path, old_str, new_str)
                elif command == "insert":
                    new_str = kwargs.get("new_str", "")
                    insert_line = kwargs.get("insert_line", 0)
                    result = self._insert(safe_path, insert_line, new_str)
                else:
                    return ToolResult(output="", error=f"Unknown command: {command!r}")
                
                self._logger.info(f"Operation completed successfully: {command}")
                return result
                
            except PermissionError as e:
                # Handle permission errors
                error = WeebotError(
                    message=f"Permission denied accessing file: {path}",
                    code=ErrorCode.UNAUTHORIZED_ACCESS,
                    severity=ErrorSeverity.WARNING,
                    remediation="Check file permissions or use a different location."
                )
                self._error_handler.handle(error, operation="file_editor.execute")
                
                return ToolResult(
                    output="",
                    error=get_user_message(error, is_developer=False)
                )
                
            except FileNotFoundError as e:
                error = WeebotError(
                    message=f"File not found: {path}",
                    code=ErrorCode.RESOURCE_NOT_FOUND,
                    severity=ErrorSeverity.WARNING,
                )
                return ToolResult(
                    output="",
                    error=f"File not found. Please check the path and try again. [Reference: {correlation_id}]"
                )
                
            except Exception as e:
                # Handle unexpected errors
                error = WeebotError(
                    message=f"Unexpected error during {command}: {str(e)}",
                    code=ErrorCode.INTERNAL_ERROR,
                    severity=ErrorSeverity.ERROR,
                    cause=e
                )
                self._error_handler.handle(error, operation="file_editor.execute")
                
                self._logger.error(
                    f"Unexpected error in file_editor",
                    extra={
                        "command": command,
                        "error": str(e),
                        "correlation_id": correlation_id
                    },
                    exc_info=True
                )
                
                # Return safe error message to user
                return ToolResult(
                    output="",
                    error=(
                        "An unexpected error occurred while processing your request. "
                        f"Please try again. If the problem persists, contact support "
                        f"with reference: {correlation_id}"
                    )
                )
    
    def _view(self, path: Path, view_range: list[int] | None) -> ToolResult:
        """View file contents or directory listing."""
        try:
            if path.is_dir():
                items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name))
                lines = [
                    f"{'DIR ' if p.is_dir() else 'FILE'}  {p.name}" 
                    for p in items
                ]
                return ToolResult(output="\n".join(lines) or "(empty directory)")
            
            # It's a file
            content = path.read_text(encoding="utf-8", errors="replace")
            numbered = [
                f"{i + 1:4}: {line}" 
                for i, line in enumerate(content.splitlines())
            ]
            
            if view_range and len(view_range) == 2:
                start, end = view_range
                numbered = numbered[start - 1:end]
            
            return ToolResult(output="\n".join(numbered))
            
        except UnicodeDecodeError:
            return ToolResult(
                output="",
                error="Cannot display file: Binary file or unsupported encoding"
            )
    
    def _create(self, path: Path, text: str) -> ToolResult:
        """Create a new file."""
        # Check if file already exists
        if path.exists():
            return ToolResult(
                output="",
                error=f"File already exists: {path}. Use str_replace to modify existing files."
            )
        
        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        path.write_text(text, encoding="utf-8")
        
        self._logger.info(f"Created file: {path}")
        return ToolResult(output=f"Created {path} ({len(text)} characters)")
    
    def _str_replace(self, path: Path, old_str: str, new_str: str) -> ToolResult:
        """Replace text in file."""
        if not path.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        
        content = path.read_text(encoding="utf-8")
        
        if old_str not in content:
            return ToolResult(
                output="",
                error=f"String not found in file. The file may have changed."
            )
        
        new_content = content.replace(old_str, new_str, 1)
        path.write_text(new_content, encoding="utf-8")
        
        self._logger.info(f"Modified file: {path}")
        return ToolResult(output=f"Successfully replaced text in {path}")
    
    def _insert(self, path: Path, insert_line: int, new_str: str) -> ToolResult:
        """Insert text at line."""
        if not path.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines = new_str.splitlines(keepends=True)
        new_lines = [ln if ln.endswith("\n") else ln + "\n" for ln in new_lines]
        
        lines[insert_line:insert_line] = new_lines
        path.write_text("".join(lines), encoding="utf-8")
        
        self._logger.info(f"Inserted {len(new_lines)} lines in {path}")
        return ToolResult(
            output=f"Inserted {len(new_lines)} line(s) at position {insert_line} in {path}"
        )


# =============================================================================
# USAGE EXAMPLE
# =============================================================================

async def example_usage():
    """Example of how the secure file editor works."""
    
    editor = StrReplaceEditorTool()
    
    # Example 1: Legitimate operation
    result = await editor.execute(
        command="view",
        path="./my_project/src/main.py"
    )
    print(result.output)  # Success!
    
    # Example 2: Path traversal attempt (BLOCKED)
    result = await editor.execute(
        command="view",
        path="../../../../Windows/System32/config/SAM"
    )
    print(result.error)
    # Output: "Security alert: The specified path contains potentially 
    #          dangerous patterns. Please use a path within your workspace. 
    #          [Reference: fe_123456789_view]"
    
    # Example 3: Path outside workspace (BLOCKED)
    result = await editor.execute(
        command="view",
        path="C:/Users/OtherUser/Documents/secret.txt"
    )
    print(result.error)
    # Output: "Invalid path: The specified location is outside the allowed 
    #          workspace. Please use a relative path within your project 
    #          directory. [Reference: fe_123456789_view]"
