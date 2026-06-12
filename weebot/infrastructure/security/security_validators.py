"""Input validators for preventing injection attacks and path traversal."""
from __future__ import annotations

import re
import base64
import binascii
from pathlib import Path
from typing import Pattern
from dataclasses import dataclass
from enum import Enum, auto

from weebot.config.settings import WORKSPACE_ROOT


class ValidationResult(Enum):
    VALID = auto()
    INVALID_PATH = auto()
    INJECTION_DETECTED = auto()
    ENCODED_PAYLOAD = auto()
    DANGEROUS_PATTERN = auto()


@dataclass
class ValidationReport:
    """Detailed validation result."""
    result: ValidationResult
    message: str
    sanitized_value: str | None = None
    matched_pattern: str | None = None


class PathValidator:
    """
    Secure path validation preventing directory traversal attacks.
    
    Security Features:
    - Resolves and normalizes paths
    - Enforces workspace boundary
    - Blocks symlink traversal
    - Validates path components
    """
    
    # Dangerous path patterns
    DANGEROUS_PATTERNS: list[Pattern] = [
        re.compile(r"\.\.[\\/]"),  # ../ or ..\
        re.compile(r"[\\/]\.\.[\\/]"),  # /../
        re.compile(r"^\.\."),  # Starting with ..
        re.compile(r"%2e%2e", re.IGNORECASE),  # URL encoded ..
        re.compile(r"0x2e0x2e"),  # Hex encoded ..
        re.compile(r"\x00"),  # Null byte injection
        re.compile(r"[~`$|&;<>]"),  # Shell metacharacters
    ]
    
    # Allowed file extensions for write operations
    ALLOWED_EXTENSIONS: set[str] = {
        # Source and config
        ".txt", ".md", ".py", ".pyi", ".json", ".yaml", ".yml",
        ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".xml", ".csv",
        ".log", ".ini", ".cfg", ".conf", ".sql", ".sh",
        ".ps1", ".bat", ".cmd",
        # Scaffolding and tooling files
        ".toml", ".lock", ".env", ".example",
        ".gitignore", ".gitkeep", ".gitattributes",
        ".dockerignore", ".editorconfig",
        ".prettierrc", ".eslintrc",
        ".flake8", ".mypy", ".pylintrc",
        ".nvmrc", ".node-version",
        ".rst", ".tex",       # documentation
        ".tf", ".tfvars",     # Terraform
    }
    
    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace = (workspace_root or WORKSPACE_ROOT).resolve()
        self._blocked_paths = self._init_blocked_paths()
    
    def _init_blocked_paths(self) -> set[Path]:
        """Initialize set of system paths that should never be accessed."""
        import sys
        if sys.platform == 'win32':
            return {
                Path("C:/Windows").resolve(),
                Path("C:/Program Files").resolve(),
                Path("C:/ProgramData").resolve(),
                Path.home().joinpath("AppData/Local/Microsoft/Windows"),
            }
        else:
            return {
                Path("/etc").resolve(),
                Path("/bin").resolve(),
                Path("/sbin").resolve(),
                Path("/usr/bin").resolve(),
                Path("/root").resolve(),
            }
    
    def validate(self, path: str | Path, allow_create: bool = False) -> ValidationReport:
        """
        Validate a path for safe file operations.
        
        Args:
            path: The path to validate
            allow_create: Whether the path can be created if it doesn't exist
            
        Returns:
            ValidationReport with detailed result
        """
        path_str = str(path)

        # Normalize MINGW/Git Bash POSIX drive paths: /c/Users/... → C:\Users\...
        import re as _re
        _mingw = _re.match(r'^/([a-zA-Z])/(.*)', path_str)
        if _mingw:
            import os as _os
            path_str = f"{_mingw.group(1).upper()}:{_os.sep}{_mingw.group(2).replace('/', _os.sep)}"

        # Check for null bytes
        if "\x00" in path_str:
            return ValidationReport(
                result=ValidationResult.INJECTION_DETECTED,
                message="Null byte injection detected",
                matched_pattern="null_byte"
            )
        
        # Check for encoded traversal attempts
        encoded_check = self._check_encoded_traversal(path_str)
        if encoded_check:
            return encoded_check
        
        # Normalize and resolve the path
        try:
            input_path = Path(path_str).expanduser().resolve()
        except (OSError, ValueError) as e:
            return ValidationReport(
                result=ValidationResult.INVALID_PATH,
                message=f"Invalid path format: {e}"
            )
        
        # Check if path is within workspace
        try:
            input_path.relative_to(self.workspace)
        except ValueError:
            # Path is outside workspace - check if it's a blocked system path
            for blocked in self._blocked_paths:
                try:
                    input_path.relative_to(blocked)
                    return ValidationReport(
                        result=ValidationResult.INVALID_PATH,
                        message=f"Access to system directory blocked: {blocked}"
                    )
                except ValueError:
                    continue
            
            # Not a blocked path but outside workspace
            return ValidationReport(
                result=ValidationResult.INVALID_PATH,
                message=f"Path must be within workspace: {self.workspace}"
            )
        
        # Check for dangerous patterns in path components
        for component in input_path.parts:
            for pattern in self.DANGEROUS_PATTERNS:
                if pattern.search(component):
                    return ValidationReport(
                        result=ValidationResult.INJECTION_DETECTED,
                        message=f"Dangerous pattern detected in path: {component}",
                        matched_pattern=pattern.pattern
                    )
        
        # Check file extension if it's a file path
        if input_path.suffix and not allow_create:
            if input_path.suffix.lower() not in self.ALLOWED_EXTENSIONS:
                return ValidationReport(
                    result=ValidationResult.DANGEROUS_PATTERN,
                    message=f"File extension not allowed: {input_path.suffix}",
                    sanitized_value=str(input_path.with_suffix(".txt"))
                )
        
        return ValidationReport(
            result=ValidationResult.VALID,
            message="Path is valid",
            sanitized_value=str(input_path)
        )
    
    def _check_encoded_traversal(self, path: str) -> ValidationReport | None:
        """Check for various encoding tricks used in path traversal."""
        # URL encoding
        url_decoded = path
        try:
            from urllib.parse import unquote
            url_decoded = unquote(path)
            if ".." in url_decoded and ".." not in path:
                return ValidationReport(
                    result=ValidationResult.ENCODED_PAYLOAD,
                    message="URL-encoded path traversal detected",
                    matched_pattern="url_encoding"
                )
        except ImportError:
            pass
        
        # Base64 encoding attempt (common in exploits)
        try:
            if len(path) % 4 == 0 and re.match(r'^[A-Za-z0-9+/=]+$', path):
                decoded = base64.b64decode(path).decode('utf-8', errors='ignore')
                if ".." in decoded or "/" in decoded:
                    return ValidationReport(
                        result=ValidationResult.ENCODED_PAYLOAD,
                        message="Base64-encoded path detected",
                        matched_pattern="base64_encoding"
                    )
        except (binascii.Error, UnicodeDecodeError):
            pass
        
        return None
    
    def get_safe_path(self, path: str | Path) -> Path:
        """
        Get a safe path, raising SecurityError if invalid.
        
        Args:
            path: The path to validate and sanitize
            
        Returns:
            Resolved Path within workspace
            
        Raises:
            SecurityError: If path is invalid or dangerous
        """
        report = self.validate(path)
        if report.result != ValidationResult.VALID:
            raise SecurityError(
                message=report.message,
                error_code="PATH_VALIDATION_FAILED",
                details={"matched_pattern": report.matched_pattern}
            )
        return Path(report.sanitized_value or path).resolve()


class CommandValidator:
    """
    Validates shell commands and Python code for dangerous patterns.
    
    Prevents:
    - Command injection via shell metacharacters
    - Path traversal in commands
    - Encoded command payloads
    - Script injection attacks
    """
    
    # PowerShell dangerous cmdlets and aliases
    POWERSHELL_DANGEROUS: list[Pattern] = [
        re.compile(r'\bformat-volume\b', re.IGNORECASE),
        re.compile(r'\bformat\s+[a-z]:', re.IGNORECASE),
        re.compile(r'\bInvoke-Expression\b|\biex\b', re.IGNORECASE),
        re.compile(r'\bInvoke-Command\b|\bicm\b', re.IGNORECASE),
        re.compile(r'\bStart-Process\b.*-Credential', re.IGNORECASE),
        re.compile(r'\bNew-LocalUser\b|\bSet-LocalUser\b', re.IGNORECASE),
        re.compile(r'\bAdd-WindowsCapability\b|\bRemove-WindowsFeature\b', re.IGNORECASE),
        re.compile(r'-EncodedCommand', re.IGNORECASE),
        # Narrowed: target explicit execution-policy bypass, not the word 'bypass' anywhere
        re.compile(r'-ExecutionPolicy\s+Bypass', re.IGNORECASE),
        re.compile(r'-ep\s+bypass', re.IGNORECASE),
    ]
    
    # Bash dangerous commands
    BASH_DANGEROUS: list[Pattern] = [
        re.compile(r'\bmkfs\b'),
        re.compile(r'\bdd\s+if='),
        re.compile(r':\(\)\{\s*:\|:&\s*\};:'),  # Fork bomb
        re.compile(r'\beval\s+\$'),
        re.compile(r'\bbase64\s+-d.*\|'),
        re.compile(r'`.*`'),  # Backtick command substitution
        # Narrowed: require non-whitespace content of 3+ chars to avoid flagging
        # PowerShell subexpressions like $($items.Count) or $() (empty)
        re.compile(r'\$\([^)]{3,}\)'),  # $() with at least 3 non-')' chars content
    ]
    
    # Python dangerous patterns
    PYTHON_DANGEROUS: list[Pattern] = [
        re.compile(r'\b__import__\s*\(\s*["\']os["\']'),
        re.compile(r'\bimport\s+os\s*;\s*os\.system'),
        re.compile(r'\bsubprocess\.call\s*\(\s*["\']'),
        re.compile(r'\beval\s*\('),
        re.compile(r'\bexec\s*\('),
        re.compile(r'\bcompile\s*\('),
        re.compile(r'\b__builtins__\b'),
        re.compile(r'\b__subclasses__\b'),
        re.compile(r'importlib\.'),  # Dynamic imports
    ]
    
    def __init__(self) -> None:
        self.path_validator = PathValidator()
    
    def validate_powershell(self, command: str) -> ValidationReport:
        """Validate PowerShell command for dangerous patterns."""
        # Check for encoded commands
        if "-enc" in command.lower() or "-encodedcommand" in command.lower():
            return ValidationReport(
                result=ValidationResult.INJECTION_DETECTED,
                message="Encoded PowerShell commands are not allowed",
                matched_pattern="-EncodedCommand"
            )
        
        # Check for dangerous patterns
        for pattern in self.POWERSHELL_DANGEROUS:
            if pattern.search(command):
                return ValidationReport(
                    result=ValidationResult.DANGEROUS_PATTERN,
                    message=f"Dangerous PowerShell pattern detected",
                    matched_pattern=pattern.pattern
                )
        
        return ValidationReport(
            result=ValidationResult.VALID,
            message="PowerShell command is valid",
            sanitized_value=command.strip()
        )
    
    def validate_bash(self, command: str) -> ValidationReport:
        """Validate Bash command for dangerous patterns.

        PowerShell commands should NOT be validated against bash patterns.
        Detects PowerShell via common cmdlet prefixes and skips bash checks.
        """
        # PowerShell commands should not be validated against bash patterns.
        # Detect via common PowerShell cmdlet prefixes.
        _POWERSHELL_INDICATORS = (
            'get-', 'set-', 'new-', 'remove-', 'invoke-',
            'write-output', 'write-host', 'get-childitem',
        )
        cmd_lower = command.lower()
        if any(ind in cmd_lower for ind in _POWERSHELL_INDICATORS):
            return ValidationReport(
                result=ValidationResult.VALID,
                message="Skipping bash validation for PowerShell command",
            )

        for pattern in self.BASH_DANGEROUS:
            if pattern.search(command):
                return ValidationReport(
                    result=ValidationResult.DANGEROUS_PATTERN,
                    message="Dangerous Bash pattern detected",
                    matched_pattern=pattern.pattern
                )
        
        return ValidationReport(
            result=ValidationResult.VALID,
            message="Bash command is valid"
        )
    
    def validate_python(self, code: str) -> ValidationReport:
        """Validate Python code for dangerous patterns."""
        for pattern in self.PYTHON_DANGEROUS:
            if pattern.search(code):
                return ValidationReport(
                    result=ValidationResult.DANGEROUS_PATTERN,
                    message="Dangerous Python pattern detected",
                    matched_pattern=pattern.pattern
                )
        
        # Check for imports that could be dangerous
        # Split into two tiers:
        # - _BLOCKED_IMPORTS: always blocked (DANGEROUS_PATTERN, "not allowed")
        # - _CONFIRM_IMPORTS: requires confirmation (DANGEROUS_PATTERN, "requires confirmation")
        _BLOCKED_IMPORTS: set[str] = {'ctypes', 'mmap', 'builtins'}
        _CONFIRM_IMPORTS: set[str] = {'socket', 'sys'}
        import_pattern = re.compile(r'^\s*import\s+(\w+)|^\s*from\s+(\w+)\s+import', re.MULTILINE)
        
        for match in import_pattern.finditer(code):
            module = match.group(1) or match.group(2)
            if module in _BLOCKED_IMPORTS:
                return ValidationReport(
                    result=ValidationResult.DANGEROUS_PATTERN,
                    message=f"Import of '{module}' is not allowed",
                    matched_pattern=f"import {module}"
                )
            if module in _CONFIRM_IMPORTS:
                return ValidationReport(
                    result=ValidationResult.DANGEROUS_PATTERN,
                    message=f"Import of '{module}' requires confirmation",
                    matched_pattern=f"import {module}"
                )
        
        return ValidationReport(
            result=ValidationResult.VALID,
            message="Python code is valid"
        )


class InputSanitizer:
    """
    General input sanitization utilities.
    
    Provides:
    - SQL injection prevention
    - HTML/JS sanitization
    - Log injection prevention
    - General string sanitization
    """
    
    # SQL injection patterns
    SQL_PATTERNS: list[Pattern] = [
        re.compile(r"(\%27)|(\')|(\-\-)|(\%23)|(#)", re.IGNORECASE),
        re.compile(r"((\%3D)|(=))[^\n]*((\%27)|(\')|(\-\-)|(\%3B)|(;))", re.IGNORECASE),
        re.compile(r"\w*((\%27)|(\'))((\%6F)|o|(\%4F))((\%72)|r|(\%52))", re.IGNORECASE),
        re.compile(r"((\%27)|(\'))union", re.IGNORECASE),
        re.compile(r"exec(\s|\+)+(s|x)p\w+", re.IGNORECASE),
        re.compile(r"UNION\s+SELECT", re.IGNORECASE),
        re.compile(r"INSERT\s+INTO", re.IGNORECASE),
        re.compile(r"DELETE\s+FROM", re.IGNORECASE),
        re.compile(r"DROP\s+TABLE", re.IGNORECASE),
    ]
    
    # HTML/Script injection patterns
    HTML_PATTERNS: list[Pattern] = [
        re.compile(r"<script[^>]*>[\s\S]*?</script>", re.IGNORECASE),
        re.compile(r"javascript:", re.IGNORECASE),
        re.compile(r"on\w+\s*=", re.IGNORECASE),  # onclick, onerror, etc.
        re.compile(r"<iframe", re.IGNORECASE),
        re.compile(r"<object", re.IGNORECASE),
        re.compile(r"<embed", re.IGNORECASE),
    ]
    
    @classmethod
    def sanitize_for_sql(cls, value: str) -> str:
        """Basic SQL injection prevention."""
        # This is a last resort - always use parameterized queries!
        sanitized = value
        for pattern in cls.SQL_PATTERNS:
            if pattern.search(sanitized):
                sanitized = pattern.sub("[REDACTED]", sanitized)
        return sanitized
    
    @classmethod
    def sanitize_for_html(cls, value: str) -> str:
        """Remove dangerous HTML patterns."""
        import html
        # First escape HTML entities
        sanitized = html.escape(value)
        return sanitized
    
    @classmethod
    def sanitize_for_logs(cls, value: str) -> str:
        """
        Prevent log injection attacks.
        
        Removes newlines that could be used to inject fake log entries.
        """
        # Replace newlines to prevent log injection
        sanitized = value.replace('\n', '\\n').replace('\r', '\\r')
        # Limit length
        if len(sanitized) > 1000:
            sanitized = sanitized[:997] + "..."
        return sanitized
    
    @classmethod
    def sanitize_api_key(cls, value: str | None) -> str:
        """Mask API keys for safe logging."""
        if not value:
            return "[NOT_SET]"
        if len(value) <= 8:
            return "***"
        return value[:4] + "..." + value[-4:]
    
    @classmethod
    def contains_sql_injection(cls, value: str) -> bool:
        """Check if value contains SQL injection patterns."""
        return any(pattern.search(value) for pattern in cls.SQL_PATTERNS)
    
    @classmethod
    def contains_html_injection(cls, value: str) -> bool:
        """Check if value contains HTML/Script injection patterns."""
        return any(pattern.search(value) for pattern in cls.HTML_PATTERNS)

# =============================================================================
# Security Error Classes — re-exported from domain layer
# =============================================================================
# These classes are defined in weebot/domain/exceptions.py to maintain
# domain purity and prevent reverse dependencies from core → infrastructure.
from weebot.domain.exceptions import (
    SecurityException as SecurityError,
    ValidationException as ValidationError,
    InjectionDetectedError,
    PathTraversalError,
    SandboxViolationError,
    UnauthorizedAccessError,
)
