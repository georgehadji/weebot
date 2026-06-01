"""Continuation detector — enriches short follow-up prompts with the original task.

Extracted from PlanActFlow to isolate the prompt-enrichment concern
into its own service with a single responsibility.

When a user sends a very short response ("proceed", "continue", "yes")
the system enriches it with the original task description so the planner
always sees the real goal rather than a vague continuation word.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Short follow-up words that carry no task meaning on their own.
# Any prompt consisting of just these words (case-insensitive) will
# be enriched with the original task description.
CONTINUATION_WORDS: frozenset[str] = frozenset({
    "proceed", "continue", "go", "next", "yes", "ok", "okay",
    "do it", "do that", "sure", "go ahead", "start", "",
})


class ContinuationDetector:
    """Detects and enriches short/vague continuation prompts.

    Usage:
        detector = ContinuationDetector()
        effective = detector.resolve_prompt(
            user_prompt=prompt,
            original_task=session.context.get("_original_task", ""),
            event_count=len(session.events),
        )
    """

    @staticmethod
    def is_continuation(text: str) -> bool:
        """Check if *text* is a continuation word or short phrase.

        Args:
            text: The user's input string (already stripped).

        Returns:
            True if the text is a known continuation word.
        """
        return text.strip().lower() in CONTINUATION_WORDS

    @staticmethod
    def is_vague(text: str) -> bool:
        """Check if *text* is too short/vague to be a standalone prompt.

        Args:
            text: The user's input string (already stripped).

        Returns:
            True if the text is 3 words or fewer.
        """
        return len(text.strip().split()) <= 3

    @classmethod
    def resolve_prompt(
        cls,
        user_prompt: str,
        original_task: str,
        event_count: int = 0,
    ) -> str:
        """Resolve the effective prompt, enriching vague continuations.

        Args:
            user_prompt: The raw user input.
            original_task: The original task description from session context.
            event_count: Number of events already in the session (0 = fresh).

        Returns:
            The effective prompt — enriched with original_task if
            the input was a continuation and there's session history.
        """
        stripped = user_prompt.strip().lower()

        if (
            original_task
            and (stripped in CONTINUATION_WORDS or cls.is_vague(stripped))
            and event_count > 0
        ):
            logger.debug(
                "Enriched short prompt %r with original task for re-planning",
                user_prompt,
            )
            return original_task

        return user_prompt
