"""CQRS (Command Query Responsibility Segregation) with Mediator pattern.

This module provides:
- Command and Query base classes
- Command and Query handlers
- Mediator for dispatching commands and queries
- Pre-built commands and handlers for common operations

Example:
    # Create mediator
    mediator = Mediator()
    
    # Register handlers
    mediator.register_command_handler(CreatePlanCommand, CreatePlanHandler())
    mediator.register_query_handler(GetSessionQuery, GetSessionHandler(repo))
    
    # Execute
    result = await mediator.send(CreatePlanCommand(session_id="s1", prompt="Do something"))
    session = await mediator.query(GetSessionQuery(session_id="s1"))
"""
from weebot.application.cqrs.base import (
    Command,
    CommandHandler,
    CommandResult,
    PipelineBehavior,
    Query,
    QueryHandler,
    QueryResult,
)
from weebot.application.cqrs.commands import (
    AnswerUserCommand,
    ArchiveSessionCommand,
    CancelSessionCommand,
    CompactMemoryCommand,
    CreatePlanCommand,
    ExecuteStepCommand,
    UpdatePlanCommand,
    AskUserCommand,
)
try:
    from weebot.application.cqrs.commands import AnswerUserCommand
except ImportError:
    AnswerUserCommand = None
from weebot.application.cqrs.handlers import (
    ArchiveSessionHandler,
    CancelSessionHandler,
    CompactMemoryHandler,
    CreatePlanHandler,
    ExecuteStepHandler,
    GetSessionHandler,
    GetSessionStatusHandler,
    ListSessionsHandler,
    UpdatePlanHandler,
    register_default_handlers,
)
from weebot.application.cqrs.mediator import (
    HandlerNotRegisteredError,
    LoggingBehavior,
    Mediator,
    MediatorError,
    ValidationBehavior,
    ValidationGateBehavior,
)
from weebot.application.cqrs.queries import (
    GetActiveTasksQuery,
    GetPlanQuery,
    GetSessionHistoryQuery,
    GetSessionQuery,
    GetSessionStatusQuery,
    GetSimilarSessionsQuery,
    ListSessionsQuery,
    SearchSessionsQuery,
)

__all__ = [
    # Base classes
    "Command",
    "CommandHandler",
    "CommandResult",
    "PipelineBehavior",
    "Query",
    "QueryHandler",
    "QueryResult",
    # Mediator
    "Mediator",
    "MediatorError",
    "HandlerNotRegisteredError",
    "LoggingBehavior",
    "ValidationBehavior",
    "ValidationGateBehavior",
    # Commands
    "CreatePlanCommand",
    "ExecuteStepCommand",
    "UpdatePlanCommand",
    "AskUserCommand",
    "AnswerUserCommand",
    "CompactMemoryCommand",
    "CancelSessionCommand",
    "ArchiveSessionCommand",
    # Queries
    "GetSessionQuery",
    "ListSessionsQuery",
    "GetSessionHistoryQuery",
    "GetActiveTasksQuery",
    "GetSessionStatusQuery",
    "GetPlanQuery",
    "SearchSessionsQuery",
    "GetSimilarSessionsQuery",
    # Handlers
    "CreatePlanHandler",
    "ExecuteStepHandler",
    "UpdatePlanHandler",
    "CancelSessionHandler",
    "CompactMemoryHandler",
    "ArchiveSessionHandler",
    "GetSessionHandler",
    "ListSessionsHandler",
    "GetSessionStatusHandler",
    "register_default_handlers",
]
