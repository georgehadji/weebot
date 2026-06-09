"""Task routing domain models — classify and route user queries to the right flow.

Enhancement 6 — Neural Task Router.  Every incoming query is classified into
a TaskCategory (casual, code, research, file_ops, mcp, complex) with a
complexity estimate.  Based on the category+complexity pair, a TaskRoute is
produced that specifies the flow type, tool restrictions, and mandatory rules.

This replaces the current approach where ALL queries enter PlanActFlow.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskCategory(str, Enum):
    """Classification of a user query by domain."""

    CASUAL = "casual"          # "hi", "hello", "tell me a joke"
    CODE = "code"              # "write a python script", "debug this"
    RESEARCH = "research"      # "find information about", "search for"
    FILE_OPS = "file_ops"      # "rename file", "create folder"
    MCP = "mcp"                # "connect to external tool"
    COMPLEX = "complex"        # Multi-step task requiring planning
    UNKNOWN = "unknown"        # Fallback — routes to complex


class TaskComplexity(str, Enum):
    """Estimated complexity of a query."""

    LOW = "low"      # Single tool call or no tools needed
    HIGH = "high"    # Multi-step, requires planning


class TaskRoute(BaseModel):
    """Routing decision for a user query."""

    category: TaskCategory = Field(default=TaskCategory.UNKNOWN)
    complexity: TaskComplexity = Field(default=TaskComplexity.HIGH)
    flow_type: str = Field(
        default="plan_act",
        description="Which flow to use: 'plan_act', 'chat', or 'mcp'",
    )
    tool_restriction: str = Field(
        default="admin_role",
        description="Tool role to use: 'admin_role', 'researcher_role', 'code_only', etc.",
    )
    mandatory_rules: list[str] = Field(
        default_factory=list,
        description="Rule files from config/prompts/rules/ to inject",
    )
    parallel_subtasks: list[dict] = Field(
        default_factory=list,
        description="Sub-task descriptors for parallel execution (Phase 6). "
                    "Each entry has 'index', 'description', and 'result' keys.",
    )

    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Classification confidence",
    )
