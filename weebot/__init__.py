"""weebot: AI Agent Framework for Windows 11."""
from weebot.agent_core_v2 import WeebotAgent, AgentConfig
from weebot.ai_router import ModelRouter, TaskType
from weebot.state_manager import StateManager, ProjectStatus
from weebot.notifications import NotificationManager

__all__ = [
    "WeebotAgent",
    "AgentConfig",
    "ModelRouter",
    "TaskType",
    "StateManager",
    "ProjectStatus",
    "NotificationManager",
]
