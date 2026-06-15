"""RegressionTask — a single evaluable task for the regression suite.

Each ``RegressionTask`` has a unique ID, a prompt (the task description),
and an ``oracle`` — a deterministic checker that verifies whether the
agent's output is correct.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from pydantic import BaseModel, Field


OracleFn = Callable[[dict[str, Any]], bool]
"""Type alias for an oracle function.

The function receives the agent's output context (a dict with keys like
``stdout``, ``files_created``, ``test_results``) and returns ``True``
if the output is correct.
"""


class OracleResult(BaseModel):
    """Result of running a single oracle check."""

    passed: bool = Field(..., description="Whether the oracle check passed")
    detail: str = Field(default="", description="Human-readable detail on the result")


class RegressionTask(BaseModel):
    """A single evaluable task for the regression suite.

    Attributes:
        id: Unique task identifier.
        prompt: The task description sent to the agent.
        oracle: Optional callable that checks the agent's output.
            If None, the task is scored by pass/fail from the flow.
        expected_summary: Optional human-readable summary of what correct
            output looks like (for logging / debugging).
        metadata: Optional key-value store (e.g. source session ID).
    """

    id: str = Field(..., description="Unique task identifier")
    prompt: str = Field(..., description="Task prompt sent to the agent")
    expected_summary: str = Field(
        default="",
        description="Human-readable summary of correct output",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    _oracle: Optional[OracleFn] = None

    def evaluate(self, context: dict[str, Any]) -> OracleResult:
        """Evaluate the agent's output against this task's oracle.

        Args:
            context: The agent's output context (stdout, files, test results).

        Returns:
            OracleResult with pass/fail.
        """
        if self._oracle is None:
            # No oracle — default to pass if no error in context
            return OracleResult(
                passed=not context.get("error"),
                detail="No oracle configured — defaulted from error presence",
            )
        try:
            passed = self._oracle(context)
            return OracleResult(
                passed=passed,
                detail="Oracle check passed" if passed else "Oracle check failed",
            )
        except Exception as exc:
            return OracleResult(
                passed=False,
                detail=f"Oracle raised {type(exc).__name__}: {exc}",
            )
