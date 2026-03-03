"""Domain exceptions for weebot — zero external dependencies.

This module provides backward compatibility and re-exports from the 
new error system. New code should use weebot.error_system_base directly.
"""

# Re-export from new error system for backward compatibility
try:
    from weebot.error_system_base import (
        WeebotError as _WeebotError,
        ErrorCode,
        ErrorSeverity,
        ErrorContext,
    )
    
    # Make WeebotError available
    WeebotError = _WeebotError
    
except ImportError:
    # Fallback if new system not available
    class WeebotError(Exception):
        """Base exception for all weebot errors."""
        def __init__(self, message: str, *args, **kwargs):
            self.message = message
            super().__init__(message, *args)


# Legacy exceptions maintained for backward compatibility
class BudgetExceededError(WeebotError):
    """Raised when daily AI budget is exceeded."""
    def __init__(self, message: str = "Daily AI budget exceeded", **kwargs):
        super().__init__(message, **kwargs)
        # Try to set code if using new system
        if hasattr(self, 'code'):
            from weebot.error_system_base import ErrorCode, ErrorSeverity
            self.code = ErrorCode.RESOURCE_EXHAUSTED
            self.severity = ErrorSeverity.WARNING


class SafetyError(WeebotError):
    """Raised when a safety check fails for a critical operation."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        if hasattr(self, 'code'):
            from weebot.error_system_base import ErrorCode, ErrorSeverity
            self.code = ErrorCode.SECURITY_VIOLATION
            self.severity = ErrorSeverity.ERROR


class TaskExecutionError(WeebotError):
    """Raised when a task fails after all retries."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        if hasattr(self, 'code'):
            from weebot.error_system_base import ErrorCode, ErrorSeverity
            self.code = ErrorCode.TOOL_EXECUTION_FAILED
            self.severity = ErrorSeverity.ERROR


class ProjectNotFoundError(WeebotError):
    """Raised when a project ID is not found in the repository."""
    def __init__(self, project_id: str, **kwargs):
        super().__init__(f"Project not found: {project_id}", **kwargs)
        self.project_id = project_id
        if hasattr(self, 'code'):
            from weebot.error_system_base import ErrorCode, ErrorSeverity
            self.code = ErrorCode.RESOURCE_NOT_FOUND
            self.severity = ErrorSeverity.WARNING


class CheckpointError(WeebotError):
    """Raised for checkpoint-related failures."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        if hasattr(self, 'code'):
            from weebot.error_system_base import ErrorCode, ErrorSeverity
            self.code = ErrorCode.INTERNAL_ERROR
            self.severity = ErrorSeverity.ERROR


# New security exceptions
class SecurityException(WeebotError):
    """Base for security-related exceptions."""
    pass


class ValidationException(WeebotError):
    """Input validation failed."""
    pass


# Convenience re-exports
__all__ = [
    "WeebotError",
    "BudgetExceededError",
    "SafetyError",
    "TaskExecutionError",
    "ProjectNotFoundError",
    "CheckpointError",
    "SecurityException",
    "ValidationException",
]
