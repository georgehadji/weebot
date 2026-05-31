"""weebot: AI Agent Framework for Windows 11."""
from .agent_core_v2 import WeebotAgent, AgentConfig
from .ai_router import ModelRouter, TaskType
from .state_manager import StateManager, ProjectStatus
from .notifications import NotificationManager
from .gitnexus_provider import GitNexusProvider, get_gitnexus_provider, enhance_prompt_with_code_context
from .gitnexus_config import GitNexusConfig, get_gitnexus_config
from .gitnexus_router import GitNexusRouter, AnalysisMode, get_gitnexus_router
from .rtk_ai_router import RTKAIRouter, get_rtk_ai_router
from .rtk_provider import RTKProvider, get_rtk_provider

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
