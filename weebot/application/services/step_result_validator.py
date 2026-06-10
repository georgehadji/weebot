"""StepResultValidator — lightweight quality gate on step outputs.

Two-tier: rule-based checks first (fast, free), optional LLM judge only
when rules detect a suspicious result.  Never blocks — on LLM failure,
returns ValidationResult(passed=True).

Rules:
  1. Empty output (len == 0) — always suspicious
  2. Too short (len < MIN_RESULT_CHARS) — suspicious for non-trivial steps
  3. Exact error strings wrapped in success (e.g. "None", "null", "undefined")
  4. Repetition: result == previous_result (step produced no new information)
  5. File-creation bypass: if a registered file tool succeeded (ToolStatus.CALLED,
     no error), skip text-length checks — success is the signal, not string content.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from weebot.domain.models.event import ToolStatus

logger = logging.getLogger(__name__)

MIN_RESULT_CHARS = 20
_SUSPICIOUSLY_EMPTY = frozenset({"none", "null", "undefined", "n/a", "", "false", "[]", "{}"})

# Only tools that are actually registered in the weebot tool registry.
# write_file / create_file do not exist — omitted to avoid silent no-ops.
_FILE_CREATION_TOOLS: frozenset[str] = frozenset({
    "file_editor",
    "edit_file",
})


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
        step_events: list[Any] | None = None,
    ) -> ValidationResult:
        """Run rule-based quality checks.

        Args:
            result: The string output of the completed step.
            step_description: Used to contextualise the quality hint.
            previous_result: Output of the same step on a previous attempt
                             (used to detect zero-information retries).
            step_events: Domain events emitted during this step.  When a
                         registered file-creation tool completes successfully
                         (ToolStatus.CALLED, is_error=False), the result is
                         accepted regardless of text length.

        Returns:
            ValidationResult(passed=True) when the result looks acceptable.
        """
        # — File-creation bypass: status is the signal, not string content —
        if step_events:
            for e in step_events:
                tn = getattr(e, "tool_name", "") or getattr(e, "function_name", "")
                if tn not in _FILE_CREATION_TOOLS:
                    continue
                status = getattr(e, "status", None)
                is_error = getattr(e, "is_error", False)
                result_text = str(getattr(e, "result", "") or "")
                if status == ToolStatus.CALLED and not is_error and result_text:
                    return ValidationResult(passed=True)

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
