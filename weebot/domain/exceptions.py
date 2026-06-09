"""Domain exceptions for weebot — zero external dependencies.

Domain layer must remain pure (no imports from core, infrastructure,
application, interfaces, or tools).  This module defines its own minimal
exception hierarchy rather than importing from weebot.core.error_system_base.
"""

from enum import Enum
from typing import Optional


class ErrorCode(str, Enum):
    """Error codes for categorizing domain exceptions."""
    RESOURCE_EXHAUSTED = "resource_exhausted"
    SECURITY_VIOLATION = "security_violation"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    RESOURCE_NOT_FOUND = "resource_not_found"
    INTERNAL_ERROR = "internal_error"
    VALIDATION_ERROR = "validation_error"


class ErrorSeverity(str, Enum):
    """Severity levels for domain exceptions."""
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class WeebotError(Exception):
    """Base exception for all weebot errors."""
    def __init__(self, message: str, *args, **kwargs):
        self.message = message
        self.code: Optional[ErrorCode] = None
        self.severity: Optional[ErrorSeverity] = None
        super().__init__(message, *args)


# Legacy exceptions maintained for backward compatibility
class BudgetExceededError(WeebotError):
    """Raised when daily AI budget is exceeded."""
    def __init__(self, message: str = "Daily AI budget exceeded", **kwargs):
        super().__init__(message, **kwargs)
        self.code = ErrorCode.RESOURCE_EXHAUSTED
        self.severity = ErrorSeverity.WARNING


class SafetyError(WeebotError):
    """Raised when a safety check fails for a critical operation."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.code = ErrorCode.SECURITY_VIOLATION
        self.severity = ErrorSeverity.ERROR


class TaskExecutionError(WeebotError):
    """Raised when a task fails after all retries."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.code = ErrorCode.TOOL_EXECUTION_FAILED
        self.severity = ErrorSeverity.ERROR


class AllModelsTrippedError(WeebotError):
    """Raised when every model in the LLM cascade has tripped its circuit breaker.

    This is a terminal condition — the executor cannot proceed without
    at least one working LLM.  The flow should stop and surface the error
    rather than retrying.
    """
    def __init__(self, message: str = "All models in the cascade have tripped", **kwargs):
        super().__init__(message, **kwargs)
        self.code = ErrorCode.RESOURCE_EXHAUSTED
        self.severity = ErrorSeverity.CRITICAL


class ProjectNotFoundError(WeebotError):
    """Raised when a project ID is not found in the repository."""
    def __init__(self, project_id: str, **kwargs):
        super().__init__(f"Project not found: {project_id}", **kwargs)
        self.project_id = project_id
        self.code = ErrorCode.RESOURCE_NOT_FOUND
        self.severity = ErrorSeverity.WARNING


class CheckpointError(WeebotError):
    """Raised for checkpoint-related failures."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.code = ErrorCode.INTERNAL_ERROR
        self.severity = ErrorSeverity.ERROR


# New security exceptions
class SecurityException(WeebotError):
    """Base for security-related exceptions."""
    pass


class ValidationException(WeebotError):
    """Input validation failed."""
    pass


class InjectionDetectedError(SecurityException):
    """Potential injection attack detected."""
    def __init__(self, message: str, injection_type: str = "unknown", matched_pattern: str | None = None):
        super().__init__(message)
        self.injection_type = injection_type
        self.matched_pattern = matched_pattern
        self.code = ErrorCode.SECURITY_VIOLATION
        self.severity = ErrorSeverity.ERROR


class PathTraversalError(SecurityException):
    """Attempted path traversal attack."""
    def __init__(self, path: str):
        super().__init__(f"Access denied: The specified path is outside the allowed workspace.")
        self.path = path
        self.code = ErrorCode.SECURITY_VIOLATION
        self.severity = ErrorSeverity.ERROR


class SandboxViolationError(SecurityException):
    """Code attempted to violate sandbox restrictions."""
    def __init__(self, message: str, violation_type: str = "unknown", blocked_operation: str | None = None):
        super().__init__(message)
        self.violation_type = violation_type
        self.blocked_operation = blocked_operation
        self.code = ErrorCode.SECURITY_VIOLATION
        self.severity = ErrorSeverity.ERROR


class UnauthorizedAccessError(SecurityException):
    """Attempted access to unauthorized resource."""
    def __init__(self, resource: str, required_permission: str | None = None):
        super().__init__(f"Access denied to resource: {resource}")
        self.resource = resource
        self.required_permission = required_permission
        self.code = ErrorCode.SECURITY_VIOLATION
        self.severity = ErrorSeverity.ERROR


# Convenience re-exports
__all__ = [
    "ErrorCode",
    "ErrorSeverity",
    "WeebotError",
    "BudgetExceededError",
    "SafetyError",
    "TaskExecutionError",
    "ProjectNotFoundError",
    "CheckpointError",
    "SecurityException",
    "ValidationException",
    "InjectionDetectedError",
    "PathTraversalError",
    "SandboxViolationError",
    "UnauthorizedAccessError",
]
