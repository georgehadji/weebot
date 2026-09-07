"""Audit domain models — independent verification agent (Enhancement 11).

Provides an independent layer for verifying agent outputs in multi-agent
workflows.  Defines audit dimensions, violation severities, and verdict types.
"""

from __future__ import annotations

from datetime import datetime, UTC
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class AuditDimension(str, Enum):
    """What aspect of the output to audit."""

    ACCURACY = "accuracy"  # Factually correct?
    SAFETY = "safety"  # No dangerous operations?
    COMPLIANCE = "compliance"  # Follows instructions?
    CONSISTENCY = "consistency"  # Self-consistent?
    COMPLETENESS = "completeness"  # Covers all requirements?
    INTEGRITY = "integrity"  # Did the audit itself corrupt the artifact it audited?


class ViolationSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AuditVerdict(str, Enum):
    PASS = "pass"  # No violations
    CONDITIONAL = "conditional"  # Minor violations
    FAIL = "fail"  # Critical violations found


class VerificationStatus(str, Enum):
    """Whether a verification gate actually ran, and what it found.

    Distinct from AuditVerdict: this describes gate *execution*, not the
    audit *result*. NOT_RUN must never be conflated with PASSED — a gate
    that raised must not read downstream as a gate that passed
    (LongHorizon-Harness E4 — fail closed, not fail open).
    """

    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


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
    checks_skipped: list[str] = Field(
        default_factory=list,
        description=(
            "Checks the auditor could not run — an unreadable path, a size lookup that "
            "returned nothing, an undecodable file. A PASS with a non-empty list is not "
            "the same claim as a PASS with an empty one, and before this field the two "
            "were byte-identical."
        ),
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
