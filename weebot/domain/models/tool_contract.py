"""ToolContract — per-tool Environment Contract (Tier 3.2).

Parsed from YAML files under ``config/contracts/`` (one per tool, see
``weebot/config/contracts/*.yaml`` for real examples). Captures knowledge
about a tool that a JSON-Schema ``parameters`` block cannot express:
argument coercion hints, safe defaults, patterns that should be blocked
outright, and free-text pitfalls/constraints an LLM needs to know before
calling the tool.

Maps to LIFE-HARNESS "Environment Contract Layer" (Tier 3.2).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CoercionSpec(BaseModel):
    """Expected shape of a single tool argument."""

    type: str = ""
    required: bool = False
    default: Any = None
    min: float | None = None
    max: float | None = None


class BlockPattern(BaseModel):
    """A regex pattern on one argument that should always be rejected."""

    argument: str
    pattern: str
    reason: str = ""


class ToolContract(BaseModel):
    """Environment contract for a single tool, loaded from YAML."""

    tool: str
    description: str = ""
    coercions: dict[str, CoercionSpec] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)
    block_patterns: list[BlockPattern] = Field(default_factory=list)
    pitfalls: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
