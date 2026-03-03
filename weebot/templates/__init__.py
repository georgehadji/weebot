"""Weebot Template Engine."""
from weebot.templates.parser import TemplateParser, WorkflowTemplate, TemplateValidationError
from weebot.templates.parameters import ParameterResolver, ParameterValidationError
from weebot.templates.registry import TemplateRegistry
from weebot.templates.engine import (
    TemplateEngine,
    TemplateExecutionResult,
    ExecutionContext,
)

__all__ = [
    "TemplateParser",
    "WorkflowTemplate",
    "TemplateValidationError",
    "ParameterResolver",
    "ParameterValidationError",
    "TemplateRegistry",
    "TemplateEngine",
    "TemplateExecutionResult",
    "ExecutionContext",
]

# Integration (optional - only import if needed)
try:
    from weebot.templates.integration import (
        TemplateOrchestratorIntegration,
        TemplateCLI,
        create_integrated_engine,
    )
    __all__.extend([
        "TemplateOrchestratorIntegration",
        "TemplateCLI",
        "create_integrated_engine",
    ])
except ImportError:
    pass

# Agent integration (optional)
try:
    from weebot.templates.agent_integration import (
        TemplateAgentManager,
        TemplateAgentTaskHandler,
        register_agent_handlers,
        create_agent_enabled_engine,
    )
    __all__.extend([
        "TemplateAgentManager",
        "TemplateAgentTaskHandler",
        "register_agent_handlers",
        "create_agent_enabled_engine",
    ])
except ImportError:
    pass
