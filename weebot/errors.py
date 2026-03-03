"""
Error handling system for weebot.

This module provides comprehensive error handling with:
- Structured error codes and severity levels
- User-friendly error messages
- Rich context for debugging
- Production-safe logging

Usage:
    from weebot.errors import WeebotError, ErrorCode, ErrorSeverity
    
    raise WeebotError(
        message="Database connection failed",
        code=ErrorCode.SERVICE_UNAVAILABLE,
        severity=ErrorSeverity.CRITICAL
    )
"""

# Re-export from error system modules
from weebot.error_system_base import (
    WeebotError,
    ErrorCode,
    ErrorSeverity,
    ErrorContext,
    ValidationError,
    ResourceNotFoundError,
    TimeoutError,
    APIError,
)

from weebot.error_system_handler import (
    ErrorHandler,
    handle_errors,
    handle_async_errors,
    error_boundary,
    ErrorAggregator,
    get_error_handler,
    set_error_handler,
)

from weebot.error_system_user_messages import (
    get_user_message,
    ErrorTranslator,
    UserErrorCategory,
    UserErrorMessage,
    format_error_for_json,
)

# Security errors
from weebot.security_validators import (
    SecurityError,
    ValidationError as SecurityValidationError,
    InjectionDetectedError,
    PathTraversalError,
    SandboxViolationError,
    UnauthorizedAccessError,
)

__all__ = [
    # Base errors
    "WeebotError",
    "ErrorCode",
    "ErrorSeverity",
    "ErrorContext",
    "ValidationError",
    "ResourceNotFoundError",
    "TimeoutError",
    "APIError",
    
    # Handler
    "ErrorHandler",
    "handle_errors",
    "handle_async_errors",
    "error_boundary",
    "ErrorAggregator",
    "get_error_handler",
    "set_error_handler",
    
    # User messages
    "get_user_message",
    "ErrorTranslator",
    "UserErrorCategory",
    "UserErrorMessage",
    "format_error_for_json",
    
    # Security errors
    "SecurityError",
    "SecurityValidationError",
    "InjectionDetectedError",
    "PathTraversalError",
    "SandboxViolationError",
    "UnauthorizedAccessError",
]
