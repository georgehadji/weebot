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
    mediator.register_query_handler(
        GetPlanVisualizationQuery, GetPlanVisualizationHandler(repo),
    )

    # Execute
    result = await mediator.send(CreatePlanCommand(session_id="s1", prompt="Do something"))
    plan = await mediator.query(GetPlanVisualizationQuery(session_id="s1"))
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
    CreatePlanCommand,
    ExecuteStepCommand,
    ProcessMessageCommand,
    SummarizeCommand,
    UpdatePlanCommand,
)
from weebot.application.cqrs.handlers import (
    CreatePlanHandler,
    ProcessMessageHandler,
    SummarizeHandler,
    ExecuteStepHandler,
    GetActiveSessionsHandler,
    GetCostSummaryHandler,
    GetPlanVisualizationHandler,
    UpdatePlanHandler,
    register_default_handlers,
)
from weebot.application.cqrs.mediator import (
    HandlerNotRegisteredError,
    Mediator,
    MediatorError,
)
from weebot.application.cqrs.behaviors.logging import LoggingBehavior
from weebot.application.cqrs.behaviors.validation import ValidationBehavior
from weebot.application.cqrs.behaviors.validation_gate import ValidationGateBehavior
from weebot.application.cqrs.queries import (
    GetActiveSessionsQuery,
    GetCostSummaryQuery,
    GetPlanVisualizationQuery,
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
    "ProcessMessageCommand",
    "SummarizeCommand",
    "UpdatePlanCommand",
    # Queries
    "GetActiveSessionsQuery",
    "GetCostSummaryQuery",
    "GetPlanVisualizationQuery",
    # Handlers
    "CreatePlanHandler",
    "ExecuteStepHandler",
    "ProcessMessageHandler",
    "SummarizeHandler",
    "UpdatePlanHandler",
    "GetActiveSessionsHandler",
    "GetCostSummaryHandler",
    "GetPlanVisualizationHandler",
    "register_default_handlers",
]
