"""Base classes for CQRS (Command Query Responsibility Segregation).

This module defines the core abstractions for commands, queries,
and their handlers, following Clean Architecture principles.

Commands and queries are now Pydantic BaseModel subclasses with
frozen=True config, providing automatic validation, JSON Schema
generation, and model_dump() serialisation consistent with the
domain models.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

TResult = TypeVar("TResult")


class Command(ABC, BaseModel):
    """Base class for all commands.

    Commands represent intent to change system state.
    They should be named in imperative form (e.g., CreateUserCommand).

    Subclass with BaseModel fields; frozen=True prevents mutation.

    Example:
        class CreateUserCommand(Command):
            email: str
            name: str

            model_config = ConfigDict(frozen=True)
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    def validate(self) -> None:
        """Validate the command before execution.

        Override for custom business-rule validation beyond Pydantic
        field-level checks.  Raises ValueError on invalid state.

        Pydantic field validators (Field, field_validator) are the
        preferred mechanism for robust validation.
        """
        pass


class Query(ABC, BaseModel):
    """Base class for all queries.

    Queries represent read-only operations that don't change state.
    They should be named with a prefix indicating what's being retrieved.

    Subclass with BaseModel fields; frozen=True prevents mutation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    def validate(self) -> None:
        """Validate the query before execution.

        Override for custom validation.  Pydantic field validators
        are the preferred mechanism for simple checks.
        """
        pass


class CommandResult(Generic[TResult]):
    """Result of executing a command.

    Attributes:
        success: Whether the command executed successfully.
        data: The result data (if successful).
        error: Error message (if failed).
        error_code: Machine-readable error code (if failed).
    """
    __slots__ = ("success", "data", "error", "error_code")

    def __init__(
        self,
        success: bool,
        data: TResult | None = None,
        error: str | None = None,
        error_code: str | None = None,
    ):
        self.success = success
        self.data = data
        self.error = error
        self.error_code = error_code

    @classmethod
    def ok(cls, data: TResult | None = None) -> CommandResult[TResult]:
        """Create a successful result."""
        return cls(success=True, data=data)

    @classmethod
    def fail(
        cls, error: str, error_code: str | None = None
    ) -> CommandResult[Any]:
        """Create a failed result."""
        return cls(success=False, error=error, error_code=error_code)

    def __repr__(self) -> str:
        if self.success:
            return f"CommandResult.ok({self.data!r})"
        return f"CommandResult.fail({self.error!r}, code={self.error_code!r})"


class QueryResult(Generic[TResult]):
    """Result of executing a query.

    Attributes:
        success: Whether the query executed successfully.
        data: The result data (if successful).
        error: Error message (if failed).
        resource_not_found: Whether the requested resource was not found.
    """
    __slots__ = ("success", "data", "error", "resource_not_found")

    def __init__(
        self,
        success: bool,
        data: TResult | None = None,
        error: str | None = None,
        resource_not_found: bool = False,
    ):
        self.success = success
        self.data = data
        self.error = error
        self.resource_not_found = resource_not_found

    @classmethod
    def ok(cls, data: TResult | None = None) -> QueryResult[TResult]:
        """Create a successful result."""
        return cls(success=True, data=data)

    @classmethod
    def not_found(cls, resource_name: str = "Resource") -> QueryResult[Any]:
        """Create a not-found result."""
        return cls(
            success=False,
            error=f"{resource_name} not found",
            resource_not_found=True,
        )

    @classmethod
    def fail(cls, error: str) -> QueryResult[Any]:
        """Create a failed result."""
        return cls(success=False, error=error)

    def __repr__(self) -> str:
        if self.success:
            return f"QueryResult.ok({self.data!r})"
        return f"QueryResult.fail({self.error!r})"


class CommandHandler(ABC, Generic[TResult]):
    """Base class for command handlers.

    Handlers contain the business logic for executing commands.
    Each handler should handle exactly one command type.
    """

    @abstractmethod
    async def handle(self, command: Command) -> TResult | CommandResult[TResult]:
        """Handle the command."""
        ...


class QueryHandler(ABC, Generic[TResult]):
    """Base class for query handlers.

    Handlers contain the logic for executing queries.
    Each handler should handle exactly one query type.
    """

    @abstractmethod
    async def handle(self, query: Query) -> TResult | QueryResult[TResult]:
        """Handle the query."""
        ...


class IPipelineBehavior(ABC):
    """Interface for pipeline behaviors (middleware).

    Behaviors wrap command/query execution to add cross-cutting
    concerns like logging, validation, telemetry, etc.
    """

    @abstractmethod
    async def handle(
        self,
        request: Command | Query,
        next_callable: Callable[[], Any],
    ) -> Any:
        """Handle the request through the pipeline."""
        ...


# Alias for backward compatibility and convenience
PipelineBehavior = IPipelineBehavior
