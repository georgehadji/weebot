"""Task type classification enum — pure domain value type.

Defined in the domain layer so that infrastructure adapters and application
services can both reference it without cross-layer coupling.
"""
from enum import Enum


class TaskType(Enum):
    """Classification of task types for routing and model selection."""
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    ARCHITECTURE = "architecture"
    DOCUMENTATION = "documentation"
    ANALYSIS = "analysis"
    CREATIVE = "creative"
    CHAT = "chat"
    REASONING = "reasoning"
    AGENTIC = "agentic"
