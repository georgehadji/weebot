"""Structured output models for reliable agent communication.

This module provides Pydantic models for enforcing structured JSON output
from the agent, enabling programmatic handling of responses and improving
reliability.

Based on patterns from The Dev Squad analysis.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class TaskStatus(str, Enum):
    """Agent task completion status."""

    SUCCESS = "success"  # All tasks completed successfully
    PARTIAL = "partial"  # Some tasks done, need retry or user input
    FAILED = "failed"  # Critical failure, should stop
    NEEDS_CLARIFICATION = "needs_clarification"  # Ask user for more info


class CodeChange(BaseModel):
    """A single code change proposed by the agent."""

    file_path: str = Field(
        ..., description="Path to the file to modify (relative to project root)"
    )
    change_type: Literal["create", "modify", "delete"] = Field(
        ..., description="Type of change to make"
    )
    description: str = Field(
        ..., description="Human-readable description of what changed"
    )
    reasoning: str = Field(..., description="Why this change is needed")
    code: Optional[str] = Field(
        None, description="Actual code content (for create/modify operations)"
    )

    @field_validator("file_path")
    @classmethod
    def no_path_traversal(cls, v: str) -> str:
        """Prevent directory traversal attacks."""
        if ".." in v:
            raise ValueError(f"Path cannot contain '..': {v}")
        if v.startswith("/"):
            raise ValueError(f"Path must be relative, not absolute: {v}")
        if v.startswith("\\"):
            raise ValueError(f"Path must be relative, not absolute: {v}")
        return v


class BashCommand(BaseModel):
    """A shell command the agent wants to execute."""

    command: str = Field(..., description="The command to execute")
    purpose: str = Field(..., description="Why this command is needed")
    expected_output: Optional[str] = Field(
        None, description="What output is expected (for verification)"
    )
    fallback_command: Optional[str] = Field(
        None, description="Alternative command if primary fails"
    )
    requires_approval: bool = Field(
        False, description="Whether user approval is required before execution"
    )
    timeout_seconds: int = Field(
        60, ge=1, le=3600, description="Command timeout in seconds"
    )


class ValidationResult(BaseModel):
    """Result of a validation check performed by the agent."""

    check_name: str = Field(..., description="Name of the validation check")
    passed: bool = Field(..., description="Whether the check passed")
    message: str = Field(..., description="Human-readable result message")
    severity: Literal["info", "warning", "error", "critical"] = Field(
        "info", description="Severity of the result"
    )
    details: Optional[dict[str, Any]] = Field(None, description="Additional details")


class WeebotOutput(BaseModel):
    """Root structured output from the weebot agent.

    This is the standard output format that the agent must produce.
    It includes work products (code changes, commands), metadata,
    and user interaction fields.
    """

    # Core fields (required)
    status: TaskStatus = Field(
        ..., description="Overall task status indicating completion level"
    )
    message: str = Field(
        ..., description="Human-readable summary of what was done"
    )
    reasoning: str = Field(
        ..., description="Agent's step-by-step thought process"
    )

    # Work products
    code_changes: list[CodeChange] = Field(
        default_factory=list, description="Code changes to apply"
    )
    bash_commands: list[BashCommand] = Field(
        default_factory=list, description="Shell commands to execute"
    )
    validation_results: list[ValidationResult] = Field(
        default_factory=list, description="Results of validation checks"
    )

    # User interaction
    requires_user_input: bool = Field(
        False, description="Whether user input is needed to proceed"
    )
    suggested_questions: list[str] = Field(
        default_factory=list,
        description="Questions the user could ask to clarify",
    )
    next_action: Optional[str] = Field(
        None, description="Recommended next action for the user"
    )

    # Metadata
    confidence: float = Field(
        0.5, ge=0.0, le=1.0, description="Agent's confidence in the result (0-1)"
    )
    estimated_complexity: int = Field(
        5, ge=1, le=10, description="Estimated task complexity (1-10)"
    )

    # Cost tracking (from Hyperagent analysis)
    tokens_used: int = Field(0, description="Total tokens consumed")
    prompt_tokens: int = Field(0, description="Tokens in the prompt")
    completion_tokens: int = Field(0, description="Tokens in the completion")
    estimated_cost: float = Field(0.0, description="Estimated cost in USD")
    model_used: str = Field("unknown", description="Model used for this response")
    cache_hit: bool = Field(False, description="Whether this was a cache hit")

    # Timing
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="When this output was created"
    )
    processing_time_ms: int = Field(
        0, description="Time taken to process in milliseconds"
    )


class OutputParseError(BaseModel):
    """Error information when parsing fails."""

    raw_text: str = Field(
        ..., description="The raw text that failed to parse"
    )
    error_message: str = Field(
        ..., description="Explanation of why parsing failed"
    )
    partial_output: Optional[WeebotOutput] = Field(
        None, description="Partially parsed output if available"
    )


def parse_agent_output(raw_text: str) -> WeebotOutput:
    """Parse agent output into structured format.

    Handles multiple input formats:
    - Valid JSON in markdown code blocks (```json ... ```)
    - Valid JSON without markdown
    - Invalid JSON (returns PARTIAL status with raw text)
    - Empty/whitespace input (returns FAILED status)

    Args:
        raw_text: The raw text output from the agent

    Returns:
        WeebotOutput: Structured output, or a default output indicating
        parse failure with status=PARTIAL or FAILED

    Examples:
        >>> output = parse_agent_output('{"status": "success", "message": "Done"}')
        >>> output.status
        <TaskStatus.SUCCESS: 'success'>

        >>> output = parse_agent_output("not json")
        >>> output.status
        <TaskStatus.PARTIAL: 'partial'>
    """
    # Clean the input
    text = raw_text.strip() if raw_text else ""
    if not text:
        return WeebotOutput(
            status=TaskStatus.FAILED,
            message="Empty response from agent",
            reasoning="Agent produced no output",
            confidence=0.0,
        )

    # Try to extract JSON from markdown code block
    json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # Try to find raw JSON (look for opening brace)
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            json_str = brace_match.group(0)
        else:
            json_str = text

    # Try to parse as JSON
    try:
        data = json.loads(json_str)
        return WeebotOutput.model_validate(data)
    except json.JSONDecodeError as e:
        # JSON parsing failed
        return WeebotOutput(
            status=TaskStatus.PARTIAL,
            message=text[:500],  # Include first 500 chars for context
            reasoning=f"Failed to parse JSON: {e}. Raw text preserved in message.",
            confidence=0.3,
            requires_user_input=True,
            suggested_questions=[
                "Please rephrase your request more specifically",
                "Can you break this down into smaller steps?",
            ],
        )
    except Exception as e:
        # Pydantic validation failed
        return WeebotOutput(
            status=TaskStatus.PARTIAL,
            message=text[:500],
            reasoning=f"Validation error: {e}. The output structure was invalid.",
            confidence=0.3,
            requires_user_input=True,
            suggested_questions=["The response format was invalid. Please try again."],
        )


def create_system_prompt() -> str:
    """Create the system prompt that mandates structured output.

    Returns:
        str: System prompt with schema documentation and examples
    """
    schema_example = {
        "status": "success",
        "message": "Created hello.py with a greeting function",
        "reasoning": "The user requested a simple greeting function. I created a clean implementation with docstring and type hints.",
        "code_changes": [
            {
                "file_path": "hello.py",
                "change_type": "create",
                "description": "Created greeting function",
                "reasoning": "User needs a way to print greetings",
                "code": "def greet(name: str) -> None:\n    '''Print a greeting.'''\n    print(f'Hello, {name}!')",
            }
        ],
        "bash_commands": [],
        "validation_results": [],
        "confidence": 0.95,
        "estimated_complexity": 2,
    }

    return f"""You are Weebot, an AI coding assistant. You MUST respond with valid JSON wrapped in a markdown code block.

Your response format MUST be:
```json
{json.dumps(schema_example, indent=2)}
```

Field descriptions:

REQUIRED FIELDS:
- status: One of "success" (all done), "partial" (needs more work), "failed" (critical error), "needs_clarification" (ask user)
- message: Human-readable summary of what you did (1-2 sentences)
- reasoning: Your step-by-step thought process (be specific)

WORK PRODUCTS (include when applicable):
- code_changes: List of file changes. Each change needs:
  - file_path: Relative path from project root (e.g., "src/main.py")
  - change_type: "create", "modify", or "delete"
  - description: What changed
  - reasoning: Why this change
  - code: Complete file content for "create", or specific changes for "modify"
- bash_commands: Shell commands to run. Each needs:
  - command: The actual command
  - purpose: Why it's needed
  - requires_approval: true for risky commands (deletions, system changes)
- validation_results: Checks you performed

METADATA:
- confidence: 0.0-1.0, how sure you are this is correct
- estimated_complexity: 1-10, how complex was this task

USER INTERACTION:
- requires_user_input: true if you need the user to clarify
- suggested_questions: List of questions the user could answer to help
- next_action: What should happen next

RULES:
1. ALWAYS wrap your JSON in ```json ... ```
2. NEVER include explanatory text outside the JSON block
3. If unsure, use status "needs_clarification" and explain what you need
4. Use relative paths only (e.g., "src/main.py" not "/home/user/project/src/main.py")
5. For code changes, include COMPLETE file content for "create", specific diff for "modify"
6. Set requires_approval=true for any command that could be destructive
"""


# Global constant for easy import
STRUCTURED_OUTPUT_PROMPT = create_system_prompt()


# Export all public symbols
__all__ = [
    "TaskStatus",
    "CodeChange",
    "BashCommand",
    "ValidationResult",
    "WeebotOutput",
    "OutputParseError",
    "parse_agent_output",
    "create_system_prompt",
    "STRUCTURED_OUTPUT_PROMPT",
]
