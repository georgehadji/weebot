"""Weebot domain models."""
import warnings

from weebot.domain.models.task_type import TaskType

# Suppress the module-level DeprecationWarning from legacy_models
# during this backward-compatibility re-export.  Consumers that import
# legacy_models directly will still see the warning.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from weebot.domain.legacy_models import (
        TaskStatus,
        ProjectStatus,
        Task,
        Checkpoint,
        AgentConfig,
        Project,
        Requirement,
        Role,
        AgentState,
        ToolCallSpec,
        Message,
        Memory,
        AgentRelationship,
    )

__all__ = [
    "TaskStatus",
    "ProjectStatus",
    "Task",
    "Checkpoint",
    "AgentConfig",
    "Project",
    "Requirement",
    "Role",
    "AgentState",
    "ToolCallSpec",
    "Message",
    "Memory",
    "AgentRelationship",
    "TaskType",
]
