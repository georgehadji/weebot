"""Base error classes and error classification system."""
from __future__ import annotations

import uuid
import traceback
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime


class ErrorSeverity(Enum):
    """Error severity levels for prioritization and alerting."""
    DEBUG = auto()      # Informational, no action needed
    INFO = auto()       # Normal operational messages
    WARNING = auto()    # Attention needed but not critical
    ERROR = auto()      # Operation failed but system stable
    CRITICAL = auto()   # System stability affected
    FATAL = auto()      # Complete system failure


class ErrorCode(Enum):
    """
    Standardized error codes for consistent handling.
    
    Format: CATEGORY_SPECIFIC
    """
    # General errors (1xxx)
    UNKNOWN_ERROR = "E1000"
    INTERNAL_ERROR = "E1001"
    NOT_IMPLEMENTED = "E1002"
    TIMEOUT_ERROR = "E1003"
    
    # Validation errors (2xxx)
    VALIDATION_ERROR = "E2000"
    INVALID_INPUT = "E2001"
    MISSING_REQUIRED_FIELD = "E2002"
    INVALID_FORMAT = "E2003"
    
    # Security errors (3xxx)
    SECURITY_VIOLATION = "E3000"
    UNAUTHORIZED_ACCESS = "E3001"
    INJECTION_DETECTED = "E3002"
    PATH_TRAVERSAL_BLOCKED = "E3003"
    SANDBOX_VIOLATION = "E3004"
    
    # Resource errors (4xxx)
    RESOURCE_NOT_FOUND = "E4000"
    RESOURCE_UNAVAILABLE = "E4001"
    RESOURCE_EXHAUSTED = "E4002"
    
    # External service errors (5xxx)
    API_ERROR = "E5000"
    NETWORK_ERROR = "E5001"
    SERVICE_UNAVAILABLE = "E5002"
    RATE_LIMITED = "E5003"
    
    # Tool execution errors (6xxx)
    TOOL_EXECUTION_FAILED = "E6000"
    TOOL_NOT_FOUND = "E6001"
    TOOL_TIMEOUT = "E6002"
    TOOL_VALIDATION_FAILED = "E6003"


@dataclass
class ErrorContext:
    """
    Rich context for error tracking and debugging.
    
    Attributes:
        error_id: Unique identifier for this error instance
        timestamp: When the error occurred
        correlation_id: Links related errors across the system
        user_id: ID of user who triggered the error (if applicable)
        session_id: Session identifier for grouping
        source_file: File where error originated
        line_number: Line number where error occurred
        function_name: Function where error occurred
        stack_trace: Full stack trace (sanitized in production)
        additional_data: Custom context data
    """
    error_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    source_file: Optional[str] = None
    line_number: Optional[int] = None
    function_name: Optional[str] = None
    stack_trace: Optional[str] = None
    additional_data: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self, include_stack_trace: bool = True) -> dict[str, Any]:
        """Convert context to dictionary for logging."""
        result = {
            "error_id": self.error_id,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "location": f"{self.source_file}:{self.line_number}" if self.source_file else "unknown",
            "function": self.function_name,
        }
        if include_stack_trace and self.stack_trace:
            result["stack_trace"] = self.stack_trace
        if self.additional_data:
            result["context"] = self.additional_data
        return result


class WeebotError(Exception):
    """
    Base exception class for all weebot errors.
    
    Features:
    - Unique error IDs for tracking
    - Structured error codes
    - Severity classification
    - Rich context capture
    - Safe serialization
    
    Usage:
        raise WeebotError(
            message="Database connection failed",
            code=ErrorCode.SERVICE_UNAVAILABLE,
            severity=ErrorSeverity.CRITICAL,
            remediation="Check database service status"
        )
    """
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        remediation: str = "",
        details: Optional[dict[str, Any]] = None,
        cause: Optional[Exception] = None,
        capture_context: bool = True,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.severity = severity
        self.remediation = remediation
        self.details = details or {}
        self.cause = cause
        self.context = ErrorContext()
        
        if capture_context:
            self._capture_context()
    
    def _capture_context(self) -> None:
        """Capture execution context at error site."""
        import sys
        
        # Get stack frame where exception was raised
        tb = traceback.extract_stack(limit=3)[0]
        self.context.source_file = tb.filename
        self.context.line_number = tb.lineno
        self.context.function_name = tb.name
        
        # Capture full stack trace if severity warrants it
        if self.severity in (ErrorSeverity.ERROR, ErrorSeverity.CRITICAL, ErrorSeverity.FATAL):
            self.context.stack_trace = traceback.format_exc()
    
    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"
    
    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"code={self.code.value}, "
            f"message={self.message!r}, "
            f"severity={self.severity.name}, "
            f"error_id={self.context.error_id}"
            f")"
        )
    
    def to_user_message(self, is_developer: bool = False) -> str:
        """
        Get user-appropriate error message.
        
        In production (is_developer=False), sensitive details are stripped.
        """
        if is_developer:
            return self._developer_message()
        return self._end_user_message()
    
    def _end_user_message(self) -> str:
        """Get message suitable for end users."""
        parts = [self.message]
        
        if self.remediation:
            parts.append(f"\nSuggestion: {self.remediation}")
        
        # Include error ID for support reference
        parts.append(f"\nReference: {self.context.error_id}")
        
        return "\n".join(parts)
    
    def _developer_message(self) -> str:
        """Get message with full debugging information."""
        lines = [
            f"Error [{self.code.value}]: {self.message}",
            f"  Severity: {self.severity.name}",
            f"  Error ID: {self.context.error_id}",
            f"  Location: {self.context.source_file}:{self.context.line_number}",
            f"  Function: {self.context.function_name}",
        ]
        
        if self.details:
            lines.append(f"  Details: {self.details}")
        
        if self.cause:
            lines.append(f"  Caused by: {type(self.cause).__name__}: {self.cause}")
        
        if self.context.stack_trace:
            lines.append(f"\nStack Trace:\n{self.context.stack_trace}")
        
        return "\n".join(lines)
    
    def to_log_dict(self) -> dict[str, Any]:
        """Convert to dictionary suitable for structured logging."""
        return {
            "error_code": self.code.value,
            "error_name": self.code.name,
            "severity": self.severity.name,
            "message": self.message,
            "context": self.context.to_dict(include_stack_trace=True),
            "details": self.details,
            "remediation": self.remediation,
            "cause_type": type(self.cause).__name__ if self.cause else None,
            "cause_message": str(self.cause) if self.cause else None,
        }
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_log_dict(), default=str)


class ValidationError(WeebotError):
    """Input validation failed."""
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        provided_value: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            code=ErrorCode.VALIDATION_ERROR,
            severity=ErrorSeverity.WARNING,
            **kwargs
        )
        self.field = field
        self.provided_value = provided_value


class ResourceNotFoundError(WeebotError):
    """Requested resource does not exist."""
    
    def __init__(self, resource_type: str, resource_id: str, **kwargs):
        super().__init__(
            message=f"{resource_type} not found: {resource_id}",
            code=ErrorCode.RESOURCE_NOT_FOUND,
            severity=ErrorSeverity.WARNING,
            **kwargs
        )
        self.resource_type = resource_type
        self.resource_id = resource_id


class TimeoutError(WeebotError):
    """Operation exceeded time limit."""
    
    def __init__(self, operation: str, timeout_seconds: float, **kwargs):
        super().__init__(
            message=f"Operation '{operation}' timed out after {timeout_seconds}s",
            code=ErrorCode.TIMEOUT_ERROR,
            severity=ErrorSeverity.ERROR,
            remediation="Try again with a longer timeout or check if the resource is available.",
            details={"timeout_seconds": timeout_seconds, "operation": operation},
            **kwargs
        )


class APIError(WeebotError):
    """External API call failed."""
    
    def __init__(
        self,
        service: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        **kwargs
    ):
        message = f"API call to {service} failed"
        if status_code:
            message += f" (HTTP {status_code})"
        
        super().__init__(
            message=message,
            code=ErrorCode.API_ERROR,
            severity=ErrorSeverity.ERROR,
            details={
                "service": service,
                "status_code": status_code,
                "response_preview": response_body[:200] if response_body else None,
            },
            **kwargs
        )
