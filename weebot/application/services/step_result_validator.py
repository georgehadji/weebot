"""StepResultValidator — lightweight quality gate on step outputs.

Two-tier: rule-based checks first (fast, free), optional LLM judge only
when rules detect a suspicious result.  Never blocks — on LLM failure,
returns ValidationResult(passed=True).

Rules:
  1. Empty output (len == 0) — always suspicious
  2. Too short (len < MIN_RESULT_CHARS) — suspicious for non-trivial steps
  3. Exact error strings wrapped in success (e.g. "None", "null", "undefined")
  4. Repetition: result == previous_result (step produced no new information)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MIN_RESULT_CHARS = 20
_SUSPICIOUSLY_EMPTY = frozenset({"none", "null", "undefined", "n/a", "", "false", "[]", "{}"})


@dataclass
class ValidationResult:
    passed: bool
    reason: str = ""
    quality_hint: str = ""  # injected into retry prompt if not passed


class StepResultValidator:
    """Validates a step result before the executor advances to the next step."""

    def validate(
        self,
        result: str | None,
        step_description: str,
        previous_result: str | None = None,
    ) -> ValidationResult:
        """Run rule-based quality checks.

        Args:
            result: The string output of the completed step.
            step_description: Used to contextualise the quality hint.
            previous_result: Output of the same step on a previous attempt
                             (used to detect zero-information retries).

        Returns:
            ValidationResult(passed=True) when the result looks acceptable.
        """
        if result is None or result.strip().lower() in _SUSPICIOUSLY_EMPTY:
            return ValidationResult(
                passed=False,
                reason="step returned empty or null-equivalent output",
                quality_hint=(
                    f"The previous attempt for step '{step_description}' returned "
                    f"an empty or null result. Produce concrete, non-empty output."
                ),
            )

        if len(result.strip()) < MIN_RESULT_CHARS:
            return ValidationResult(
                passed=False,
                reason=f"result too short ({len(result.strip())} chars)",
                quality_hint=(
                    f"The previous attempt for step '{step_description}' returned "
                    f"only {len(result.strip())} characters. Provide more detail."
                ),
            )

        if previous_result is not None and result.strip() == previous_result.strip():
            return ValidationResult(
                passed=False,
                reason="result identical to previous attempt — no new information",
                quality_hint=(
                    f"Step '{step_description}' returned the same output as the "
                    f"previous attempt. Try a different approach."
                ),
            )

        return ValidationResult(passed=True)
