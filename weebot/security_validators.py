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
        ".txt", ".md", ".py", ".json", ".yaml", ".yml",
        ".js", ".ts", ".html", ".css", ".xml", ".csv",
        ".log", ".ini", ".cfg", ".conf", ".sql", ".sh",
        ".ps1", ".bat", ".cmd"
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
        from weebot.errors.security_errors import SecurityError
        
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
        re.compile(r'bypass', re.IGNORECASE),
    ]
    
    # Bash dangerous commands
    BASH_DANGEROUS: list[Pattern] = [
        re.compile(r'\bmkfs\b'),
        re.compile(r'\bdd\s+if='),
        re.compile(r':\(\)\{\s*:\|:&\s*\};:'),  # Fork bomb
        re.compile(r'\beval\s+\$'),
        re.compile(r'\bbase64\s+-d.*\|'),
        re.compile(r'`.*`'),  # Backtick command substitution
        re.compile(r'\$\(.*\)'),  # $() command substitution
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
        """Validate Bash command for dangerous patterns."""
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
        dangerous_imports = {'socket', 'ctypes', 'mmap', 'sys', 'builtins'}
        import_pattern = re.compile(r'^\s*import\s+(\w+)|^\s*from\s+(\w+)\s+import', re.MULTILINE)
        
        for match in import_pattern.finditer(code):
            module = match.group(1) or match.group(2)
            if module in dangerous_imports:
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
        re.compile(r"<script[^>]*>[\\s\\S]*?</script>", re.IGNORECASE),
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
# Security Error Classes
# =============================================================================

class SecurityError(Exception):
    """
    Base class for security-related errors.
    
    Attributes:
        message: Human-readable error description
        error_code: Machine-readable error code for client handling
        details: Additional context (not exposed to users in production)
        remediation: Suggested fix for the user
    """
    
    def __init__(
        self,
        message: str,
        error_code: str = "SECURITY_VIOLATION",
        details: dict | None = None,
        remediation: str = "",
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.remediation = remediation
    
    def __str__(self) -> str:
        return f"[{self.error_code}] {self.message}"


class ValidationError(SecurityError):
    """Input validation failed."""
    
    def __init__(
        self,
        message: str,
        field: str | None = None,
        provided_value: str | None = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            **kwargs
        )
        self.field = field
        self.provided_value = provided_value


class InjectionDetectedError(SecurityError):
    """Potential injection attack detected."""
    
    def __init__(
        self,
        message: str,
        injection_type: str = "unknown",
        matched_pattern: str | None = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code="INJECTION_DETECTED",
            details={"injection_type": injection_type, "matched_pattern": matched_pattern},
            remediation="Please review your input and remove special characters or scripting content.",
            **kwargs
        )
        self.injection_type = injection_type
        self.matched_pattern = matched_pattern


class PathTraversalError(SecurityError):
    """Attempted path traversal attack."""
    
    def __init__(self, path: str, **kwargs):
        super().__init__(
            message="Access denied: The specified path is outside the allowed workspace.",
            error_code="PATH_TRAVERSAL_BLOCKED",
            details={"attempted_path": path},
            remediation="Use a path within the workspace directory.",
            **kwargs
        )


class SandboxViolationError(SecurityError):
    """Code attempted to violate sandbox restrictions."""
    
    def __init__(
        self,
        message: str,
        violation_type: str = "unknown",
        blocked_operation: str | None = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code="SANDBOX_VIOLATION",
            details={
                "violation_type": violation_type,
                "blocked_operation": blocked_operation
            },
            remediation="This operation is not permitted in the sandboxed environment.",
            **kwargs
        )


class UnauthorizedAccessError(SecurityError):
    """Attempted access to unauthorized resource."""
    
    def __init__(
        self,
        resource: str,
        required_permission: str | None = None,
        **kwargs
    ):
        super().__init__(
            message=f"Access denied to resource: {resource}",
            error_code="UNAUTHORIZED_ACCESS",
            details={"required_permission": required_permission},
            remediation="Contact your administrator if you need access to this resource.",
            **kwargs
        )
