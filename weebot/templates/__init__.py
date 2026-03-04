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

# Phase 5: Advanced Features
try:
    from weebot.templates.jinja_renderer import (
        JinjaTemplateRenderer,
        ConditionalWorkflowBuilder,
        LoopWorkflowBuilder,
        TemplateRenderError,
    )
    __all__.extend([
        "JinjaTemplateRenderer",
        "ConditionalWorkflowBuilder",
        "LoopWorkflowBuilder",
        "TemplateRenderError",
    ])
except ImportError:
    pass

try:
    from weebot.templates.versioning import (
        TemplateVersionManager,
        VersionedTemplateRegistry,
        TemplateVersion,
        VersionMigration,
    )
    __all__.extend([
        "TemplateVersionManager",
        "VersionedTemplateRegistry",
        "TemplateVersion",
        "VersionMigration",
    ])
except ImportError:
    pass

try:
    from weebot.templates.marketplace import (
        TemplateMarketplace,
        LocalTemplateRepository,
        TemplateListing,
        TemplateReview,
    )
    __all__.extend([
        "TemplateMarketplace",
        "LocalTemplateRepository",
        "TemplateListing",
        "TemplateReview",
    ])
except ImportError:
    pass

try:
    from weebot.templates.hooks import (
        HookRegistry,
        HookedTemplateEngine,
        BuiltinHooks,
        HookConditions,
        hook,
    )
    __all__.extend([
        "HookRegistry",
        "HookedTemplateEngine",
        "BuiltinHooks",
        "HookConditions",
        "hook",
    ])
except ImportError:
    pass

# Phase 6: Production Features
try:
    from weebot.templates.production import (
        ProductionTemplateEngine,
        RateLimiter,
        Authenticator,
        User,
        DatabaseManager,
        RedisCache,
        HealthChecker,
    )
    __all__.extend([
        "ProductionTemplateEngine",
        "RateLimiter",
        "Authenticator",
        "User",
        "DatabaseManager",
        "RedisCache",
        "HealthChecker",
    ])
except ImportError:
    pass

# Phase 6b: Adaptive Suggestions (EXPAND mode)
try:
    from weebot.templates.adaptive import (
        AdaptiveSuggestionEngine,
        ParameterSuggestion,
        SuggestionContext,
    )
    __all__.extend([
        "AdaptiveSuggestionEngine",
        "ParameterSuggestion",
        "SuggestionContext",
    ])
except ImportError:
    pass

try:
    from weebot.templates.feature_flags import (
        FeatureFlagManager,
        FeatureState,
        FeatureConfig,
        get_feature_flags,
    )
    __all__.extend([
        "FeatureFlagManager",
        "FeatureState",
        "FeatureConfig",
        "get_feature_flags",
    ])
except ImportError:
    pass

try:
    from weebot.templates.migrations import (
        SchemaManager,
        init_database,
    )
    __all__.extend([
        "SchemaManager",
        "init_database",
    ])
except ImportError:
    pass
