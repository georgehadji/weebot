"""weebot: AI Agent Framework for Windows 11."""
# Lazy imports — heavyweight modules are loaded on demand via __getattr__
# to keep the root namespace fast and prevent transitive layer leaks.
import typing as _t


def __getattr__(name: str) -> _t.Any:
    _LAZY_MAP = {
        "WeebotAgent": ".agent_core_v2",
        "AgentConfig": ".agent_core_v2",
        "ModelRouter": ".ai_router",
        "TaskType": ".ai_router",
        "StateManager": ".state_manager",
        "ProjectStatus": ".state_manager",
        "NotificationManager": ".notifications",
        "GitNexusProvider": ".gitnexus_provider",
        "get_gitnexus_provider": ".gitnexus_provider",
        "enhance_prompt_with_code_context": ".gitnexus_provider",
        "GitNexusConfig": ".gitnexus_config",
        "get_gitnexus_config": ".gitnexus_config",
        "GitNexusRouter": ".gitnexus_router",
        "AnalysisMode": ".gitnexus_router",
        "get_gitnexus_router": ".gitnexus_router",
        "RTKProvider": ".rtk_provider",
        "get_rtk_provider": ".rtk_provider",
        "RTKAIRouter": ".rtk_ai_router",
        "get_rtk_ai_router": ".rtk_ai_router",
    }
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], __package__)
        return getattr(mod, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "WeebotAgent",
    "AgentConfig",
    "ModelRouter",
    "TaskType",
    "StateManager",
    "ProjectStatus",
    "NotificationManager",
    "GitNexusProvider",
    "get_gitnexus_provider",
    "enhance_prompt_with_code_context",
    "GitNexusConfig",
    "get_gitnexus_config",
    "GitNexusRouter",
    "AnalysisMode",
    "get_gitnexus_router",
    "RTKProvider",
    "get_rtk_provider",
    "RTKAIRouter",
    "get_rtk_ai_router",
]
