"""Harness instruction and runtime-control domain models.

These define the behavioural surfaces that Self-Harness can evolve:
instruction blocks (bootstrap / execution / verification / failure-recovery),
runtime policy knobs, subagent declarations, and skill-selection config.

All models carry defaults so adding a new field is backward-compatible.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InstructionConfig(BaseModel):
    """Behavioural instruction surfaces — the paper's primary edit targets.

    Each field is a free-text instruction block that is appended to the
    executor's system prompt.  The Self-Harness optimizer can mutate these
    to address model-specific failure patterns.
    """

    system_prompt_extension: str = Field(
        default="",
        description="Arbitrary text appended directly to the base system prompt",
    )
    bootstrap: str = Field(
        default="",
        description="Guidance for the very first action on a task",
    )
    execution: str = Field(
        default="",
        description="Guidance for how to approach execution",
    )
    verification: str = Field(
        default="",
        description="Guidance for verifying outcomes",
    )
    failure_recovery: str = Field(
        default="",
        description="Guidance for recovering from tool-call failures",
    )

    yagni_preflight: str = Field(
        default=(
            "Before executing any step, stop at the first rung that holds:\n"
            "1. Does this step still need to be executed?\n"
            "   Previous steps may have covered it. If so, skip this step and note why.\n"
            "2. Does an existing tool call in the conversation already cover this?\n"
            "   Reuse its output instead of repeating the call.\n"
            "3. Can a single bash/python command replace the planned sequence?\n"
            "   One command is cheaper than three tool calls.\n"
            "4. Will the tool call output be smaller than the code it would produce?\n"
            "   If the output is a single line, just output it. Don't call a tool.\n"
            "5. Is the tool call necessary at all?\n"
            "   Only then: execute the planned step.\n"
            "\n"
            "After execution, append 'skipped: [X], add when [Y]' if you skipped anything.\n"
            "Never skip: validation, error handling, security checks, or accessibility.\n"
            "Active every response. No drift back to over-building.\n"
            "Based on ponytail (github.com/DietrichGebert/ponytail)."
        ),
        description=(
            "Ponytail YAGNI ladder — forces the agent to question whether each "
            "step needs to be executed, from 'skip entirely' (rung 1) to 'execute "
            "as planned' (rung 5). Based on the ponytail skill."
        ),
    )


class RuntimeControlConfig(BaseModel):
    """Runtime policy knobs — guardrails the optimizer can tighten or loosen.

    These are safety-critical.  By default all knobs are disabled (None),
    meaning no runtime-level intervention.  The Self-Harness safety gate
    (Phase 6) prevents autonomous modification of these fields.
    """

    enabled: bool = Field(
        default=False,
        description="Master switch — when False, none of the below apply",
    )
    max_recent_tool_errors: int | None = Field(
        default=None,
        description="Max consecutive tool errors before forced intervention",
    )
    max_total_tool_messages: int | None = Field(
        default=None,
        description="Max tool-call messages before forced summarisation",
    )
    loop_detection_instruction: str | None = Field(
        default=None,
        description="Instruction injected when a tool-error loop is detected",
    )


class SubagentConfig(BaseModel):
    """Subagent declarations — which subagents are available to the executor.

    Each entry defines a name, role, and optional skill assignments.
    """

    definitions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Subagent definitions: [{'name': ..., 'role': ..., 'skills': [...]}]",
    )
    max_parallel: int = Field(
        default=0,
        ge=0,
        description="Max parallel subagents (0 = disabled, 1 = serial delegation)",
    )


class SkillSelectionConfig(BaseModel):
    """Which skills are loaded into the executor's context.

    The optimizer can add/remove skills to address failure patterns.
    """

    active_skills: list[str] = Field(
        default_factory=list,
        description="Skill names to load into executor context",
    )
