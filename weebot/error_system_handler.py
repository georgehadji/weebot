"""Centralized error handling and processing."""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar, Optional
from contextlib import contextmanager

from weebot.error_system_base import WeebotError, ErrorContext, ErrorSeverity, ErrorCode


T = TypeVar('T')
logger = logging.getLogger(__name__)


class ErrorHandler:
    """
    Centralized error handler for consistent error processing.
    
    Responsibilities:
    - Error classification and routing
    - Logging with appropriate detail level
    - User notification for critical errors
    - Metrics collection
    - Recovery attempt for transient errors
    """
    
    def __init__(
        self,
        log_full_stacktraces: bool = True,
        notify_on_severity: set[ErrorSeverity] | None = None,
    ):
        self.log_full_stacktraces = log_full_stacktraces
        self.notify_on_severity = notify_on_severity or {
            ErrorSeverity.ERROR, ErrorSeverity.CRITICAL, ErrorSeverity.FATAL
        }
        self._error_counts: dict[str, int] = {}
    
    def handle(
        self,
        error: Exception,
        context: Optional[ErrorContext] = None,
        operation: str = "unknown",
        user_id: Optional[str] = None,
    ) -> WeebotError:
        """
        Process an exception and return a standardized WeebotError.
        
        Args:
            error: The caught exception
            context: Optional error context
            operation: Description of what was being attempted
            user_id: ID of the user who triggered the error
            
        Returns:
            Standardized WeebotError with full context
        """
        # Convert to WeebotError if needed
        if isinstance(error, WeebotError):
            weebot_error = error
        else:
            weebot_error = self._wrap_exception(error, operation)
        
        # Merge provided context
        if context:
            weebot_error.context.correlation_id = context.correlation_id
            weebot_error.context.user_id = user_id or context.user_id
            weebot_error.context.session_id = context.session_id
        
        # Log the error
        self._log_error(weebot_error)
        
        # Track error metrics
        self._track_error(weebot_error)
        
        # Notify if severity warrants
        if weebot_error.severity in self.notify_on_severity:
            self._notify_error(weebot_error)
        
        return weebot_error
    
    def _wrap_exception(
        self,
        error: Exception,
        operation: str,
    ) -> WeebotError:
        """Wrap a standard exception in WeebotError."""
        # Map common exception types
        error_map = {
            TimeoutError: (ErrorCode.TIMEOUT_ERROR, ErrorSeverity.ERROR),
            FileNotFoundError: (ErrorCode.RESOURCE_NOT_FOUND, ErrorSeverity.WARNING),
            PermissionError: (ErrorCode.UNAUTHORIZED_ACCESS, ErrorSeverity.ERROR),
            ConnectionError: (ErrorCode.NETWORK_ERROR, ErrorSeverity.ERROR),
            ValueError: (ErrorCode.INVALID_INPUT, ErrorSeverity.WARNING),
        }
        
        error_type = type(error)
        code, severity = error_map.get(error_type, (ErrorCode.UNKNOWN_ERROR, ErrorSeverity.ERROR))
        
        return WeebotError(
            message=f"{operation} failed: {str(error)}",
            code=code,
            severity=severity,
            cause=error,
            details={"original_error_type": error_type.__name__},
        )
    
    def _log_error(self, error: WeebotError) -> None:
        """Log error with appropriate detail level."""
        log_data = error.to_log_dict()
        
        # Use appropriate log level based on severity
        if error.severity == ErrorSeverity.DEBUG:
            logger.debug("Error occurred", extra=log_data)
        elif error.severity == ErrorSeverity.INFO:
            logger.info("Operation result", extra=log_data)
        elif error.severity == ErrorSeverity.WARNING:
            logger.warning(error.message, extra=log_data)
        elif error.severity in (ErrorSeverity.ERROR, ErrorSeverity.CRITICAL):
            logger.error(error.message, extra=log_data)
        else:  # FATAL
            logger.critical(error.message, extra=log_data)
    
    def _track_error(self, error: WeebotError) -> None:
        """Track error metrics for monitoring."""
        key = f"{error.code.value}:{error.code.name}"
        self._error_counts[key] = self._error_counts.get(key, 0) + 1
    
    def _notify_error(self, error: WeebotError) -> None:
        """Send notifications for critical errors."""
        # This could integrate with notification system
        if error.severity == ErrorSeverity.CRITICAL:
            logger.critical(
                f"CRITICAL ERROR [{error.context.error_id}]: {error.message}. "
                f"Immediate attention required!"
            )
    
    def get_error_summary(self) -> dict[str, Any]:
        """Get summary of errors tracked."""
        return {
            "total_errors": sum(self._error_counts.values()),
            "by_code": self._error_counts.copy(),
        }


# Global error handler instance
_global_handler: Optional[ErrorHandler] = None


def get_error_handler() -> ErrorHandler:
    """Get or create global error handler."""
    global _global_handler
    if _global_handler is None:
        _global_handler = ErrorHandler()
    return _global_handler


def set_error_handler(handler: ErrorHandler) -> None:
    """Set global error handler."""
    global _global_handler
    _global_handler = handler


def handle_errors(
    operation: str = "operation",
    reraise: bool = True,
    default_return: Optional[T] = None,
) -> Callable:
    """
    Decorator for consistent error handling in functions.
    
    Usage:
        @handle_errors(operation="file read", reraise=False, default_return=None)
        def read_file(path: str) -> str | None:
            return Path(path).read_text()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T | None]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T | None:
            handler = get_error_handler()
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                weebot_error = handler.handle(e, operation=operation)
                
                if reraise:
                    raise weebot_error from e
                return default_return
        
        return wrapper
    return decorator


def handle_async_errors(
    operation: str = "async operation",
    reraise: bool = True,
    default_return: Optional[T] = None,
) -> Callable:
    """Decorator for async functions."""
    def decorator(func: Callable[..., T]) -> Callable[..., T | None]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T | None:
            handler = get_error_handler()
            
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                weebot_error = handler.handle(e, operation=operation)
                
                if reraise:
                    raise weebot_error from e
                return default_return
        
        return wrapper
    return decorator


@contextmanager
def error_boundary(
    operation: str,
    correlation_id: Optional[str] = None,
    suppress: bool = False,
):
    """
    Context manager for error handling boundaries.
    
    Usage:
        with error_boundary("database transaction", correlation_id=req_id):
            db.execute(query)
    """
    handler = get_error_handler()
    context = ErrorContext(correlation_id=correlation_id)
    
    try:
        yield
    except Exception as e:
        weebot_error = handler.handle(e, context=context, operation=operation)
        if not suppress:
            raise weebot_error from e


class ErrorAggregator:
    """
    Aggregate multiple errors for batch processing.
    
    Usage:
        with ErrorAggregator("batch processing") as agg:
            for item in items:
                with agg.catch():
                    process(item)
        
        if agg.has_errors:
            raise agg.to_exception()
    """
    
    def __init__(self, operation: str, fail_fast: bool = False) -> None:
        self.operation = operation
        self.fail_fast = fail_fast
        self.errors: list[WeebotError] = []
        self.context = ErrorContext()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val and not self.errors:
            # Unhandled exception, let it propagate
            return False
        return True  # Suppress if we've collected errors
    
    @contextmanager
    def catch(self, item_identifier: Optional[str] = None):
        """Context manager to catch and aggregate errors."""
        try:
            yield
        except Exception as e:
            handler = get_error_handler()
            weebot_error = handler.handle(
                e,
                context=self.context,
                operation=f"{self.operation}:{item_identifier}" if item_identifier else self.operation
            )
            self.errors.append(weebot_error)
            
            if self.fail_fast:
                raise self.to_exception()
    
    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    @property
    def error_count(self) -> int:
        return len(self.errors)
    
    def to_exception(self) -> WeebotError:
        """Convert aggregated errors to a single exception."""
        messages = [e.message for e in self.errors[:5]]
        if len(self.errors) > 5:
            messages.append(f"... and {len(self.errors) - 5} more errors")
        
        return WeebotError(
            message=f"{self.operation} completed with {len(self.errors)} errors:\n" + "\n".join(messages),
            code=ErrorCode.UNKNOWN_ERROR,
            severity=ErrorSeverity.ERROR,
            details={
                "error_count": len(self.errors),
                "individual_errors": [e.to_log_dict() for e in self.errors],
            },
        )
