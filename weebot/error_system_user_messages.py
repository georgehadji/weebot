"""User-friendly error message translation system."""
from __future__ import annotations

from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional

from weebot.error_system_base import WeebotError, ErrorCode, ErrorSeverity


class UserErrorCategory(Enum):
    """Categories of errors from user perspective."""
    INPUT_PROBLEM = auto()      # User input issue
    PERMISSION_DENIED = auto()  # Access control
    RESOURCE_MISSING = auto()   # File/API not found
    SERVICE_ISSUE = auto()      # External service problem
    SYSTEM_ERROR = auto()       # Internal error
    SECURITY_CONCERN = auto()   # Security violation


@dataclass
class UserErrorMessage:
    """Structured user error message."""
    title: str
    message: str
    suggestion: str
    category: UserErrorCategory
    can_retry: bool
    support_reference: str


class ErrorTranslator:
    """
    Translates technical errors into user-friendly messages.
    
    Handles:
    - Stripping sensitive information
    - Appropriate technical detail level
    - Localization preparation
    - Retry guidance
    """
    
    # Mapping of error codes to user messages
    ERROR_TEMPLATES: dict[ErrorCode, tuple[str, str, str, UserErrorCategory, bool]] = {
        # General errors
        ErrorCode.UNKNOWN_ERROR: (
            "Something went wrong",
            "An unexpected error occurred while processing your request.",
            "Please try again. If the problem persists, contact support with the reference number.",
            UserErrorCategory.SYSTEM_ERROR,
            True,
        ),
        ErrorCode.TIMEOUT_ERROR: (
            "Request timed out",
            "The operation took longer than expected to complete.",
            "Please try again. The system may be experiencing high load.",
            UserErrorCategory.SERVICE_ISSUE,
            True,
        ),
        
        # Validation errors
        ErrorCode.VALIDATION_ERROR: (
            "Invalid input",
            "The information you provided doesn't meet our requirements.",
            "Please check your input and try again. Ensure all required fields are filled correctly.",
            UserErrorCategory.INPUT_PROBLEM,
            True,
        ),
        ErrorCode.INVALID_INPUT: (
            "Invalid format",
            "The data you entered is not in the expected format.",
            "Please review the input requirements and try again.",
            UserErrorCategory.INPUT_PROBLEM,
            True,
        ),
        ErrorCode.MISSING_REQUIRED_FIELD: (
            "Missing information",
            "A required field was not provided.",
            "Please fill in all required fields and try again.",
            UserErrorCategory.INPUT_PROBLEM,
            True,
        ),
        
        # Security errors
        ErrorCode.SECURITY_VIOLATION: (
            "Security alert",
            "A potential security issue was detected with your request.",
            "Please review your input. If you believe this is an error, contact support.",
            UserErrorCategory.SECURITY_CONCERN,
            False,
        ),
        ErrorCode.UNAUTHORIZED_ACCESS: (
            "Access denied",
            "You don't have permission to perform this action.",
            "Please check your permissions or contact your administrator.",
            UserErrorCategory.PERMISSION_DENIED,
            False,
        ),
        ErrorCode.INJECTION_DETECTED: (
            "Input blocked",
            "Your input contains characters or patterns that are not allowed.",
            "Please remove any special characters, scripts, or code from your input.",
            UserErrorCategory.SECURITY_CONCERN,
            True,
        ),
        ErrorCode.PATH_TRAVERSAL_BLOCKED: (
            "Invalid location",
            "The specified location is outside the allowed area.",
            "Please use a path within your workspace or project directory.",
            UserErrorCategory.INPUT_PROBLEM,
            True,
        ),
        
        # Resource errors
        ErrorCode.RESOURCE_NOT_FOUND: (
            "Not found",
            "The requested item could not be found.",
            "Please check the identifier and try again.",
            UserErrorCategory.RESOURCE_MISSING,
            False,
        ),
        ErrorCode.RESOURCE_UNAVAILABLE: (
            "Resource unavailable",
            "The required resource is currently unavailable.",
            "Please try again in a few moments.",
            UserErrorCategory.SERVICE_ISSUE,
            True,
        ),
        ErrorCode.RESOURCE_EXHAUSTED: (
            "Limit reached",
            "You've reached the limit for this resource.",
            "Please wait before trying again or upgrade your plan.",
            UserErrorCategory.SERVICE_ISSUE,
            True,
        ),
        
        # API errors
        ErrorCode.API_ERROR: (
            "Service error",
            "An external service encountered an error.",
            "Please try again. If the problem persists, the service may be experiencing issues.",
            UserErrorCategory.SERVICE_ISSUE,
            True,
        ),
        ErrorCode.NETWORK_ERROR: (
            "Connection error",
            "Could not connect to a required service.",
            "Please check your internet connection and try again.",
            UserErrorCategory.SERVICE_ISSUE,
            True,
        ),
        ErrorCode.SERVICE_UNAVAILABLE: (
            "Service unavailable",
            "A required service is currently unavailable.",
            "Please try again later. The service may be down for maintenance.",
            UserErrorCategory.SERVICE_ISSUE,
            True,
        ),
        ErrorCode.RATE_LIMITED: (
            "Too many requests",
            "You've made too many requests in a short time.",
            "Please wait a moment before trying again.",
            UserErrorCategory.SERVICE_ISSUE,
            True,
        ),
        
        # Tool errors
        ErrorCode.TOOL_EXECUTION_FAILED: (
            "Action failed",
            "The requested action could not be completed.",
            "Please check the error details and try again.",
            UserErrorCategory.SYSTEM_ERROR,
            True,
        ),
        ErrorCode.TOOL_NOT_FOUND: (
            "Action not available",
            "The requested action is not available.",
            "Please check your agent configuration.",
            UserErrorCategory.SYSTEM_ERROR,
            False,
        ),
        ErrorCode.TOOL_TIMEOUT: (
            "Action timed out",
            "The action took too long to complete.",
            "Try simplifying your request or increasing the timeout.",
            UserErrorCategory.SERVICE_ISSUE,
            True,
        ),
    }
    
    @classmethod
    def translate(
        cls,
        error: WeebotError,
        include_technical_details: bool = False,
    ) -> UserErrorMessage:
        """
        Translate a WeebotError to a user-friendly message.
        
        Args:
            error: The error to translate
            include_technical_details: Whether to include technical info
            
        Returns:
            UserErrorMessage with appropriate detail level
        """
        # Get template for error code
        template = cls.ERROR_TEMPLATES.get(error.code)
        
        if template:
            title, message, suggestion, category, can_retry = template
        else:
            # Unknown error code
            title = "Error"
            message = error.message
            suggestion = error.remediation or "Please try again or contact support."
            category = UserErrorCategory.SYSTEM_ERROR
            can_retry = error.severity not in (ErrorSeverity.FATAL, ErrorSeverity.CRITICAL)
        
        # Override with error's specific remediation if available
        if error.remediation:
            suggestion = error.remediation
        
        return UserErrorMessage(
            title=title,
            message=message,
            suggestion=suggestion,
            category=category,
            can_retry=can_retry,
            support_reference=error.context.error_id,
        )
    
    @classmethod
    def to_string(cls, error: WeebotError, is_developer: bool = False) -> str:
        """
        Convert error to formatted string.
        
        Args:
            error: The error to format
            is_developer: Whether to include technical details
            
        Returns:
            Formatted error message
        """
        if is_developer:
            return error._developer_message()
        
        user_msg = cls.translate(error, include_technical_details=False)
        
        lines = [
            f"{user_msg.title}",
            f"",
            f"{user_msg.message}",
            f"",
            f"Suggestion: {user_msg.suggestion}",
            f"",
            f"Reference: {user_msg.support_reference}",
        ]
        
        if user_msg.can_retry:
            lines.append("You can try this operation again.")
        
        return "\n".join(lines)


def get_user_message(
    error: Exception,
    is_developer: bool = False,
) -> str:
    """
    Get user-appropriate message from any exception.
    
    This is the main entry point for error message translation.
    
    Args:
        error: Any exception
        is_developer: Whether to include technical details
        
    Returns:
        Formatted error message appropriate for the audience
    """
    if isinstance(error, WeebotError):
        return ErrorTranslator.to_string(error, is_developer)
    
    # Handle standard exceptions
    if isinstance(error, FileNotFoundError):
        return f"File not found: {error.filename}\nPlease check the path and try again."
    
    if isinstance(error, PermissionError):
        return "Permission denied. You don't have access to this resource."
    
    if isinstance(error, TimeoutError):
        return "The operation timed out. Please try again."
    
    if isinstance(error, ValueError):
        return f"Invalid value: {str(error)}\nPlease check your input and try again."
    
    # Generic fallback
    if is_developer:
        import traceback
        return f"Error: {type(error).__name__}: {str(error)}\n\n{traceback.format_exc()}"
    
    return (
        "An unexpected error occurred.\n"
        "Please try again. If the problem persists, contact support."
    )


def format_error_for_json(error: WeebotError) -> dict:
    """Format error as JSON-serializable dictionary."""
    user_msg = ErrorTranslator.translate(error)
    
    return {
        "success": False,
        "error": {
            "code": error.code.value,
            "title": user_msg.title,
            "message": user_msg.message,
            "suggestion": user_msg.suggestion,
            "can_retry": user_msg.can_retry,
            "reference": user_msg.support_reference,
        }
    }
