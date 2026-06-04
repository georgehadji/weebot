"""Truth-binding domain models — deterministic response-layer guards.

Every assistant response to the user is validated against these checks
BEFORE it reaches the user. No LLM is involved in the policy path.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TruthCheck(BaseModel):
    """A single deterministic guard applied to an agent response.

    Each check is a pure Python expression evaluated in a restricted
    sandbox — no LLM call, no external IO.
    """
    name: str = Field(description="Check identifier, e.g. 'url_substitution'")
    description: str = Field(description="Human-readable explanation of what this check catches")
    severity: str = Field(description="'block' | 'warn' | 'rewrite' — action on violation")


class TruthViolation(BaseModel):
    """A single violation found by a truth check."""
    check: str = Field(description="Name of the check that fired")
    message: str = Field(description="Human-readable violation detail")
    severity: str = Field(description="'block' | 'warn' | 'rewrite'")


class TruthBindingResult(BaseModel):
    """Result of running all truth checks on a response."""
    passed: bool = Field(description="True if all checks passed")
    original_text: str = Field(default="", description="The response before binding")
    bound_text: str = Field(default="", description="The response after potential rewriting")
    violations: list[TruthViolation] = Field(
        default_factory=list,
        description="Checks that fired, in order of detection",
    )

    def has_blockers(self) -> bool:
        """True if any violation has severity 'block'."""
        return any(v.severity == "block" for v in self.violations)

    def has_rewrites(self) -> bool:
        """True if any violation has severity 'rewrite'."""
        return any(v.severity == "rewrite" for v in self.violations)
