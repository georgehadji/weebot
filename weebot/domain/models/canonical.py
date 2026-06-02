"""Canonicalization domain models — tool-call validation and correction (Tier 1.1).

The Action Canonicalizer sits between the executor and ToolCollection.execute().
It validates, coerces types, fills safe defaults, and blocks actions that would
deterministically fail.  Every canonicalization produces a CanonicalizationEvent
for audit and downstream harness evolution.

Maps to LIFE-HARNESS "Action Realization Layer" (Section 4.3.3).
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CanonicalizationVerdict(str, Enum):
    """Result of canonicalizing a tool call."""

    PASS = "pass"            # Action forwarded (possibly with corrections)
    BLOCK = "block"          # Deterministic failure — blocked with reason
    FILL_DEFAULT = "fill"    # Missing arg filled with safe default


class CanonicalizationResult(BaseModel):
    """Result of validating and canonicalizing a tool call before execution."""

    verdict: CanonicalizationVerdict = Field(default=CanonicalizationVerdict.PASS)
    original_args: dict[str, Any] = Field(default_factory=dict)
    corrected_args: dict[str, Any] = Field(default_factory=dict)
    changes: list[str] = Field(
        default_factory=list,
        description="Human-readable list of what was corrected",
    )
    block_reason: str = Field(
        default="",
        description="Populated when verdict is BLOCK",
    )
