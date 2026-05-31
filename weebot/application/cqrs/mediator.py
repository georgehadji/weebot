"""Mediator — central dispatcher for commands and queries."""
from __future__ import annotations

from typing import Any, Callable, Type, TypeVar

from weebot.application.cqrs.base import (
    Command,
    CommandHandler,
    CommandResult,
    IPipelineBehavior,
    PipelineBehavior,
    Query,
    QueryHandler,
    QueryResult,
)

TResult = TypeVar("TResult")


class MediatorError(Exception):
    """Exception raised by the Mediator."""
    pass


class HandlerNotRegisteredError(MediatorError):
    """Raised when no handler is registered for a command/query type."""
    pass


class Mediator:
    """Central dispatcher for commands and queries.

    The Mediator pattern decouples command/query senders from handlers,
    allowing for centralized handling, pipeline behaviors (middleware),
    and cleaner architecture.

    Example:
        mediator = Mediator()

        # Register handlers
        mediator.register_command_handler(CreatePlanCommand, CreatePlanHandler())
        mediator.register_query_handler(GetSessionQuery, GetSessionHandler(repo))

        # Add pipeline behavior
        mediator.add_pipeline_behavior(LoggingBehavior())

        # Execute commands
        result = await mediator.send(CreatePlanCommand(session_id="s1", prompt="Do something"))

        # Execute queries
        session_result = await mediator.query(GetSessionQuery(session_id="s1"))
        if session_result.success:
            print(session_result.data)
    """

    def __init__(self):
        """Initialize the mediator."""
        self._command_handlers: dict[Type[Command], CommandHandler] = {}
        self._query_handlers: dict[Type[Query], QueryHandler] = {}
        self._behaviors: list[IPipelineBehavior] = []

    def register_command_handler(
        self,
        command_type: Type[Command],
        handler: CommandHandler,
    ) -> None:
        """Register a handler for a command type.

        Args:
            command_type: The type of command to handle.
            handler: The handler for this command type.

        Raises:
            ValueError: If a handler is already registered for this type.
        """
        if command_type in self._command_handlers:
            raise ValueError(f"Handler already registered for {command_type.__name__}")

        self._command_handlers[command_type] = handler

    def register_query_handler(
        self,
        query_type: Type[Query],
        handler: QueryHandler,
    ) -> None:
        """Register a handler for a query type.

        Args:
            query_type: The type of query to handle.
            handler: The handler for this query type.

        Raises:
            ValueError: If a handler is already registered for this type.
        """
        if query_type in self._query_handlers:
            raise ValueError(f"Handler already registered for {query_type.__name__}")

        self._query_handlers[query_type] = handler

    def unregister_command_handler(self, command_type: Type[Command]) -> None:
        """Unregister a command handler.

        Args:
            command_type: The command type to unregister.
        """
        if command_type in self._command_handlers:
            del self._command_handlers[command_type]

    def unregister_query_handler(self, query_type: Type[Query]) -> None:
        """Unregister a query handler.

        Args:
            query_type: The query type to unregister.
        """
        if query_type in self._query_handlers:
            del self._query_handlers[query_type]

    def add_pipeline_behavior(self, behavior: IPipelineBehavior) -> None:
        """Add a pipeline behavior (middleware).

        Behaviors are executed in the order they are added.

        Args:
            behavior: The behavior to add.
        """
        self._behaviors.append(behavior)

    def remove_pipeline_behavior(self, behavior: IPipelineBehavior) -> None:
        """Remove a pipeline behavior.

        Args:
            behavior: The behavior to remove.
        """
        if behavior in self._behaviors:
            self._behaviors.remove(behavior)

    async def _execute_with_pipeline(
        self,
        request: Command | Query,
        handler_func: Callable[[], Any],
    ) -> Any:
        """Execute a request through the pipeline of behaviors.

        Args:
            request: The command or query to execute.
            handler_func: The final handler function.

        Returns:
            The result of the execution.
        """
        # Current index in the behaviors list
        index = 0

        async def resolve_next():
            nonlocal index
            if index < len(self._behaviors):
                behavior = self._behaviors[index]
                index += 1
                return await behavior.handle(request, resolve_next)
            else:
                return await handler_func()

        return await resolve_next()

    async def send(self, command: Command) -> CommandResult:
        """Send a command to its handler.

        Args:
            command: The command to execute.

        Returns:
            CommandResult with execution details.

        Raises:
            HandlerNotRegisteredError: If no handler is registered for this command.
        """
        command_type = type(command)
        handler = self._command_handlers.get(command_type)

        if handler is None:
            raise HandlerNotRegisteredError(
                f"No handler registered for {command_type.__name__}"
            )

        try:
            # Build and execute pipeline
            async def execute_handler():
                return await handler.handle(command)

            if self._behaviors:
                result = await self._execute_with_pipeline(command, execute_handler)
            else:
                result = await execute_handler()

            # Wrap result if needed
            if isinstance(result, CommandResult):
                return result
            return CommandResult.ok(result)

        except Exception as e:
            return CommandResult.fail(
                error=str(e),
                error_code=type(e).__name__,
            )

    async def query(self, query: Query) -> QueryResult:
        """Send a query to its handler.

        Args:
            query: The query to execute.

        Returns:
            QueryResult with execution details.

        Raises:
            HandlerNotRegisteredError: If no handler is registered for this query.
        """
        query_type = type(query)
        handler = self._query_handlers.get(query_type)

        if handler is None:
            raise HandlerNotRegisteredError(
                f"No handler registered for {query_type.__name__}"
            )

        try:
            # Build and execute pipeline
            async def execute_handler():
                return await handler.handle(query)

            if self._behaviors:
                result = await self._execute_with_pipeline(query, execute_handler)
            else:
                result = await execute_handler()

            # Wrap result if needed
            if isinstance(result, QueryResult):
                return result

            if result is None:
                return QueryResult.not_found()

            return QueryResult.ok(result)

        except Exception as e:
            return QueryResult.fail(str(e))

    def is_command_registered(self, command_type: Type[Command]) -> bool:
        """Check if a handler is registered for a command type.

        Args:
            command_type: The command type to check.

        Returns:
            True if a handler is registered.
        """
        return command_type in self._command_handlers

    def is_query_registered(self, query_type: Type[Query]) -> bool:
        """Check if a handler is registered for a query type.

        Args:
            query_type: The query type to check.

        Returns:
            True if a handler is registered.
        """
        return query_type in self._query_handlers

    def get_registered_commands(self) -> list[Type[Command]]:
        """Get all registered command types.

        Returns:
            List of registered command types.
        """
        return list(self._command_handlers.keys())

    def get_registered_queries(self) -> list[Type[Query]]:
        """Get all registered query types.

        Returns:
            List of registered query types.
        """
        return list(self._query_handlers.keys())


class LoggingBehavior(IPipelineBehavior):
    """Pipeline behavior that logs command/query execution.

    Example:
        mediator = Mediator()
        mediator.add_pipeline_behavior(LoggingBehavior())
    """

    def __init__(self, logger_name: str = "weebot.cqrs"):
        """Initialize the logging behavior.

        Args:
            logger_name: Name for the logger.
        """
        import logging
        self._logger = logging.getLogger(logger_name)

    async def handle(
        self,
        request: Command | Query,
        next_callable: Callable,
    ) -> Any:
        """Log request execution."""
        request_name = type(request).__name__
        self._logger.debug(f"Executing {request_name}")

        try:
            result = await next_callable()
            self._logger.debug(f"Completed {request_name}")
            return result
        except Exception as e:
            self._logger.error(f"Failed {request_name}: {e}")
            raise


class ValidationBehavior(PipelineBehavior):
    """Pipeline behavior that validates requests before execution.
    
    Expects requests to have a `validate()` method that raises
    ValueError for invalid requests.
    
    Example:
        @dataclass(frozen=True)
        class CreatePlanCommand(Command):
            session_id: str
            prompt: str
            
            def validate(self):
                if not self.session_id:
                    raise ValueError("session_id is required")
                if not self.prompt:
                    raise ValueError("prompt is required")
        
        mediator = Mediator()
        mediator.add_pipeline_behavior(ValidationBehavior())
    """
    
    async def handle(
        self,
        request: Command | Query,
        next_callable: Callable,
    ) -> Any:
        """Validate and execute request."""
        # Check if request has validate method
        if hasattr(request, "validate") and callable(request.validate):
            # Run validation
            if asyncio.iscoroutinefunction(request.validate):
                await request.validate()
            else:
                request.validate()
        
        return await next_callable()


import asyncio


class ValidationGateBehavior(IPipelineBehavior):
    """Pipeline behaviour that validates skill edits before acceptance.

    Intercepts ApplySkillEditsCommand results and runs the candidate
    skill through a validation gate.  If validation fails, the command
    result is replaced with a failure.

    Register on the mediator:
        mediator = Mediator()
        mediator.add_pipeline_behavior(ValidationGateBehavior(validation_runner))
    """

    def __init__(self, validation_runner=None):
        """Optional — validation runner can be set later via setter."""
        self._runner = validation_runner

    def set_runner(self, validation_runner) -> None:
        self._runner = validation_runner

    async def handle(
        self,
        request: Command | Query,
        next_callable: Callable[[], Any],
    ) -> Any:
        result = await next_callable()

        # Only gate ApplySkillEditsCommand results
        if not isinstance(request, Command):
            return result

        cmd_name = type(request).__name__
        if cmd_name != "ApplySkillEditsCommand":
            return result

        if self._runner is None:
            return result

        # Extract candidate info from the successful result
        if isinstance(result, CommandResult) and result.success:
            data = result.data or {}
            candidate_content = data.get("candidate_content", "")
            skill_name = data.get("skill_name", "")
            validation_ids = getattr(request, "validation_task_ids", [])

            if not validation_ids:
                # No validation tasks configured — accept unconditionally
                return result

            validation_result = await self._runner.validate(
                candidate_content=candidate_content,
                validation_task_ids=list(validation_ids),
                baseline_score=None,
            )

            if not validation_result.passed:
                return CommandResult.fail(
                    error=(
                        f"Validation gate rejected: "
                        f"Δ={validation_result.score_delta:.3f}, "
                        f"candidate={validation_result.candidate_score:.3f}"
                    ),
                    error_code="VALIDATION_GATE_REJECTED",
                )

        return result
