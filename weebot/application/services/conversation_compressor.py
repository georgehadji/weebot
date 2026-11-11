"""ConversationCompressor — one cheap-model call that summarizes a slice of the conversation.

It is the model call behind the `SummarizeMiddle` pass (`context_passes.py`). It receives
the exact middle to summarize; choosing the head and tail is the pipeline's job, so there
is no second slicing here.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from weebot.application.ports.llm_port import LLMPort
from weebot.config.constants import TEMPERATURE_DETERMINISTIC, MAX_TOKENS_SHORT

logger = logging.getLogger(__name__)

__all__ = ["ConversationCompressor"]

_COMPRESS_SYSTEM = (
    "You are a concise summarizer. Given a conversation excerpt between an AI agent "
    "and its tools, produce a factual 3-7 sentence summary of: what was attempted, "
    "what was found, and any key facts discovered. No commentary, just facts.\n"
    "In addition, reproduce VERBATIM every user-stated instruction that constrains "
    "how the agent should behave for the rest of the session (approval requirements, "
    "prohibitions, output-format rules, stated preferences). These are not task "
    "progress and must not be paraphrased away — a task-only summary silently drops "
    "them and the agent then violates them."
)


class ConversationCompressor:
    """Summarize a slice of messages with the cheap model.

    Args:
        llm: LLMPort instance to use for the summarization call.
        cheap_model: Model ID for the summary call (defaults to MODEL_BUDGET).
    """

    def __init__(self, llm: LLMPort, cheap_model: str | None = None) -> None:
        self._llm = llm
        if cheap_model is None:
            from weebot.config.model_refs import MODEL_BUDGET

            cheap_model = MODEL_BUDGET
        self._cheap_model = cheap_model

    async def summarize(self, messages: Sequence[dict[str, Any]]) -> str:
        """Return a factual summary of *messages*, or "" when the call fails.

        An empty string is the failure signal: the caller falls back deterministically
        instead of committing an error string as if it were a summary.
        """
        transcript_parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content") or ""
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            if content:
                transcript_parts.append(f"{role.upper()}: {content[:2000]}")

        if not transcript_parts:
            return "(empty conversation section)"

        transcript = "\n\n".join(transcript_parts)
        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _COMPRESS_SYSTEM},
                    {"role": "user", "content": f"Summarize this conversation:\n\n{transcript}"},
                ],
                model=self._cheap_model,
                tools=None,
                tool_choice=None,
                temperature=TEMPERATURE_DETERMINISTIC,
                max_tokens=MAX_TOKENS_SHORT,
            )
            return (response.content or "").strip()
        except Exception as exc:
            logger.warning("Compressor LLM call failed: %s", exc)
            return ""
