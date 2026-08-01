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

__all__.extend([
    "TemplateMarketplace",
    "LocalTemplateRepository",
    "TemplateListing",
    "TemplateReview",
])

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
__all__.extend([
    "ProductionTemplateEngine",
    "RateLimiter",
    "Authenticator",
    "User",
    "DatabaseManager",
    "RedisCache",
    "HealthChecker",
])

# Phase 6b: Adaptive Suggestions (EXPAND mode) — lazy, pulls sqlalchemy
__all__.extend([
    "AdaptiveSuggestionEngine",
    "ParameterSuggestion",
    "SuggestionContext",
])

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

# Schema migrations — lazy, pulls sqlalchemy
__all__.extend([
    "SchemaManager",
    "init_database",
])


# ── Lazily-loaded heavy submodules (PEP 562) ──────────────────────────
# `production` pulls in sqlalchemy and `marketplace` pulls in requests —
# together ~8 s of import time that every `python -m cli.main ...` paid just
# to import this package.  Neither is needed on a normal CLI path, so they
# load on first attribute access instead.  `from weebot.templates import
# ProductionTemplateEngine` still works; it just imports at that moment.
_LAZY_SUBMODULES: dict[str, str] = {
    "TemplateMarketplace": "marketplace",
    "LocalTemplateRepository": "marketplace",
    "TemplateListing": "marketplace",
    "TemplateReview": "marketplace",
    "ProductionTemplateEngine": "production",
    "RateLimiter": "production",
    "Authenticator": "production",
    "User": "production",
    "DatabaseManager": "production",
    "RedisCache": "production",
    "HealthChecker": "production",
    "AdaptiveSuggestionEngine": "adaptive",
    "ParameterSuggestion": "adaptive",
    "SuggestionContext": "adaptive",
    "SchemaManager": "migrations",
    "init_database": "migrations",
}


def __getattr__(name: str):
    """Resolve lazily-loaded names from heavy optional submodules."""
    submodule = _LAZY_SUBMODULES.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    try:
        mod = importlib.import_module(f"weebot.templates.{submodule}")
    except ImportError as exc:  # optional dependency missing
        raise AttributeError(
            f"{name!r} requires the optional 'weebot.templates.{submodule}' "
            f"module, which failed to import: {exc}"
        ) from exc
    value = getattr(mod, name)
    globals()[name] = value  # cache — subsequent lookups skip __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(set(list(globals()) + __all__))
