"""Weebot models package.

This package contains Pydantic models for structured data exchange,
including the structured output protocol for agent communication.
"""

from weebot.models.structured_output import (
    BashCommand,
    CodeChange,
    OutputParseError,
    STRUCTURED_OUTPUT_PROMPT,
    TaskStatus,
    ValidationResult,
    WeebotOutput,
    create_system_prompt,
    parse_agent_output,
)

__all__ = [
    "BashCommand",
    "CodeChange",
    "OutputParseError",
    "STRUCTURED_OUTPUT_PROMPT",
    "TaskStatus",
    "ValidationResult",
    "WeebotOutput",
    "create_system_prompt",
    "parse_agent_output",
]
