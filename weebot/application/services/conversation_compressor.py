"""ConversationCompressor — summarizes middle turns to shrink context window usage.

Inspired by hermes-agent's context engine pattern:
  - Protect first KEEP_HEAD turns (head of conversation)
  - Protect last KEEP_TAIL turns (recent context most relevant to current step)
  - Summarize the middle via a single cheap-model LLM call
  - Replace compressed region with one summary system message

This preserves the conversational head (which anchors the task) and the
recent tail (most relevant to the current execution step) while dramatically
reducing token count for long-running sessions.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from weebot.application.ports.llm_port import LLMPort

logger = logging.getLogger(__name__)

__all__ = ["ConversationCompressor", "KEEP_HEAD", "KEEP_TAIL"]

KEEP_HEAD: int = 3
"""Number of turns to always preserve at the start of the buffer."""

KEEP_TAIL: int = 6
"""Number of turns to always preserve at the end of the buffer."""

_COMPRESS_SYSTEM = (
    "You are a concise summarizer. Given a conversation excerpt between an AI agent "
    "and its tools, produce a factual 3-7 sentence summary of: what was attempted, "
    "what was found, and any key facts discovered. No commentary, just facts."
)


class ConversationCompressor:
    """Summarize the middle portion of a conversation buffer in-place.

    Args:
        llm: LLMPort instance to use for the summarization call.
        cheap_model: Model ID for the summary call (defaults to MODEL_BUDGET).
        keep_head: Turns to protect at the start.
        keep_tail: Turns to protect at the end.
    """

    def __init__(
        self,
        llm: LLMPort,
        cheap_model: Optional[str] = None,
        keep_head: int = KEEP_HEAD,
        keep_tail: int = KEEP_TAIL,
    ) -> None:
        self._llm = llm
        self._keep_head = keep_head
        self._keep_tail = keep_tail
        if cheap_model is None:
            from weebot.config.model_refs import MODEL_BUDGET
            cheap_model = MODEL_BUDGET
        self._cheap_model = cheap_model

    async def compress(
        self, buffer: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Return a new buffer with middle turns replaced by a summary message.

        If the buffer is too short to compress (head + tail >= len),
        returns the original buffer unchanged.

        Args:
            buffer: List of chat message dicts with 'role' and 'content'.

        Returns:
            Compressed buffer. Middle turns replaced by a single system message.
        """
        total = len(buffer)
        min_compressible = self._keep_head + self._keep_tail + 1
        if total < min_compressible:
            logger.debug(
                "Buffer too short to compress (%d < %d turns), skipping",
                total,
                min_compressible,
            )
            return buffer

        head = buffer[: self._keep_head]
        middle = buffer[self._keep_head : total - self._keep_tail]
        tail = buffer[total - self._keep_tail :]

        summary = await self._summarize(middle)
        summary_msg: Dict[str, Any] = {
            "role": "system",
            "content": (
                f"[Context summary — {len(middle)} turns compressed]\n{summary}"
            ),
        }

        compressed = head + [summary_msg] + tail
        logger.info(
            "Compressed conversation buffer: %d → %d messages (%d summarized)",
            total,
            len(compressed),
            len(middle),
        )
        return compressed

    async def _summarize(self, messages: List[Dict[str, Any]]) -> str:
        """Call cheap model to produce a factual summary of *messages*."""
        transcript_parts: List[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content") or ""
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            if content:
                transcript_parts.append(f"{role.upper()}: {content[:2000]}")

        if not transcript_parts:
            return "(empty conversation section)"

        transcript = "\n\n".join(transcript_parts)
        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _COMPRESS_SYSTEM},
                    {
                        "role": "user",
                        "content": f"Summarize this conversation:\n\n{transcript}",
                    },
                ],
                model=self._cheap_model,
                tools=None,
                tool_choice=None,
                temperature=0.0,
                max_tokens=512,
            )
            return response.content or "(summary unavailable)"
        except Exception as exc:
            logger.warning("Compressor LLM call failed: %s", exc)
            return f"(compression failed: {exc})"
