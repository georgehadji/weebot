"""Audit domain models — independent verification agent (Enhancement 11).

Provides an independent layer for verifying agent outputs in multi-agent
workflows.  Defines audit dimensions, violation severities, and verdict types.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class AuditDimension(str, Enum):
    """What aspect of the output to audit."""
    ACCURACY = "accuracy"           # Factually correct?
    SAFETY = "safety"               # No dangerous operations?
    COMPLIANCE = "compliance"       # Follows instructions?
    CONSISTENCY = "consistency"     # Self-consistent?
    COMPLETENESS = "completeness"   # Covers all requirements?


class ViolationSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AuditVerdict(str, Enum):
    PASS = "pass"           # No violations
    CONDITIONAL = "conditional"  # Minor violations
    FAIL = "fail"           # Critical violations found


class Violation(BaseModel):
    """A single issue found during audit."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    dimension: AuditDimension = Field(default=AuditDimension.ACCURACY)
    severity: ViolationSeverity = Field(default=ViolationSeverity.MEDIUM)
    description: str = Field(default="")
    location: str = Field(default="", description="Which part of the output")
    recommendation: str = Field(default="")


class AuditReport(BaseModel):
    """Complete audit result for a session or sub-agent output."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(default="")
    agent_id: str = Field(default="")
    verdict: AuditVerdict = Field(default=AuditVerdict.PASS)
    violations: list[Violation] = Field(default_factory=list)
    summary: str = Field(default="")
    score: float = Field(default=1.0, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
