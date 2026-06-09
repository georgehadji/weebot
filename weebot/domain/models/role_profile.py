"""RoleProfile — per-model harness configuration.

Extends ROLE_MODEL_CONFIG with optional tools_override, excluded_tools,
extra_middleware, and rubric_prompt. Falls back to the simple model list
for backward compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RoleProfile:
    """Profile for a functional agent role with model-specific configuration.

    Args:
        models: Ordered list of model IDs (primary → fallback1 → fallback2).
        tools_override: Optional subset of tools for this role. If None, uses role default.
        excluded_tools: Tools to remove from this role's tool list.
        extra_middleware: Additional middleware class names for this role.
        rubric_prompt: Optional response-grading rubric for this role's model.
    """
    models: list[str] = field(default_factory=list)
    tools_override: Optional[list[str]] = None
    excluded_tools: list[str] = field(default_factory=list)
    extra_middleware: list[str] = field(default_factory=list)
    rubric_prompt: Optional[str] = None
