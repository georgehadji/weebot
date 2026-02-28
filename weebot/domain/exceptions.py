"""Domain exceptions for weebot — zero external dependencies."""


class WeebotError(Exception):
    """Base exception for all weebot errors."""


class BudgetExceededError(WeebotError):
    """Raised when daily AI budget is exceeded."""


class SafetyError(WeebotError):
    """Raised when a safety check fails for a critical operation."""


class TaskExecutionError(WeebotError):
    """Raised when a task fails after all retries."""


class ProjectNotFoundError(WeebotError):
    """Raised when a project ID is not found in the repository."""


class CheckpointError(WeebotError):
    """Raised for checkpoint-related failures."""
