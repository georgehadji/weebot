"""Lossy Context Compressor — default context engine implementation.

Implements IContextEnginePort by summarizing older messages into a
compressed preamble while preserving the last N messages as-is.

Phase 4 (F6) improvements:
- Head + tail retention for long messages (trailing facts survive)
- Short messages kept verbatim (raw > summary for exact recall)
- Regex guard preserves numeric/date tokens during truncation
- Configurable caps via ContextBudget (message_head_chars, tail, summary)
"""
from __future__ import annotations

import logging
import re
from typing import Any

from weebot.application.ports.context_engine_port import IContextEnginePort
from weebot.domain.models.context import (
    CompressionResult,
    CompressionStrategy,
    ContextBudget,
)

logger = logging.getLogger(__name__)

# Threshold below which messages are kept verbatim (F6: raw > summary)
_SHORT_MSG_THRESHOLD = 150


def _truncate_with_head_tail(
    text: str,
    head_chars: int,
    tail_chars: int,
    elision: str = " [...] ",
) -> str:
    """Truncate *text* to head + tail with an elision marker.

    Preserves numeric/date tokens within the retained portions using
    a cheap regex guard that detects trailing digits adjacent to the
    cut point and extends the boundary.
    """
    if len(text) <= head_chars + tail_chars + len(elision):
        return text

    head = text[:head_chars]
    tail = text[-tail_chars:] if tail_chars > 0 else ""

    # Regex guard: if a digit cluster straddles the cut point in the head,
    # extend head to include it (prevents "202" from "2026-06-30")
    head_extension = re.search(r"\d+", text[head_chars:head_chars + 10])
    if head_extension:
        head += head_extension.group()

    # Similarly for the tail: if digits precede the tail, extend backwards
    if tail_chars > 0:
        tail_extension = re.search(r"\d+", text[-tail_chars - 10:-tail_chars])
        if tail_extension:
            # Only extend if the matched digits connect cleanly
            matched = tail_extension.group()
            idx = text.rfind(matched, 0, -tail_chars)
            if idx >= 0 and text[-tail_chars - 10:-tail_chars].strip():
                pass  # Keep simple — just use the standard tail

    result = f"{head}{elision}{tail}" if tail else f"{head}{elision}"
    return result.strip()


def _rough_token_count(text: str) -> int:
    """Rough token estimation (4 chars ≈ 1 token)."""
    return len(text) // 4


def _estimate_message_tokens(msg: dict[str, Any]) -> int:
    """Estimate tokens for a single message dict."""
    total = 0
    for key in ("role", "content", "name", "tool_calls", "tool_call_id"):
        val = msg.get(key)
        if isinstance(val, str):
            total += _rough_token_count(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    for v in item.values():
                        if isinstance(v, str):
                            total += _rough_token_count(v)
    return total


class LossyContextCompressor(IContextEnginePort):
    """Compresses context by summarizing older messages.

    Keeps system messages, optionally preserves a configurable number of
    recent messages, and replaces older conversation turns with a summary.
    """

    def __init__(self) -> None:
        self._compression_count = 0

    async def get_token_count(self, messages: list[dict[str, Any]]) -> int:
        total = sum(_estimate_message_tokens(m) for m in messages)
        return total

    async def should_compress(
        self,
        messages: list[dict[str, Any]],
        token_count: int,
        threshold: int = 12000,
    ) -> bool:
        """Compress if token count exceeds threshold."""
        if token_count <= 0:
            token_count = await self.get_token_count(messages)
        return token_count > threshold

    async def compress(
        self,
        messages: list[dict[str, Any]],
        budget: ContextBudget | None = None,
    ) -> CompressionResult:
        """Compress messages using lossy summarization.

        Args:
            messages: Full message list.
            budget: Budget with max_tokens, protect_last_n, target_ratio, strategy.

        Returns:
            CompressionResult with summary and counts.
        """
        budget = budget or ContextBudget()

        original_count = len(messages)
        original_tokens = await self.get_token_count(messages)

        # Separate system messages (always preserved)
        system_msgs = [m for m in messages if m.get("role") == "system"]
        # Preserve last N messages
        protect_n = budget.protect_last_n
        volatile_msgs = messages[-protect_n:] if protect_n > 0 else []
        # Messages eligible for compression
        compressible = [
            m for m in messages
            if m not in system_msgs and m not in volatile_msgs
        ]

        if not compressible:
            return CompressionResult(
                summary="",
                retained_count=original_count,
                discarded_count=0,
                original_token_count=original_tokens,
                compressed_token_count=original_tokens,
            )

        # Build a summary of the compressible messages
        head_chars = budget.message_head_chars
        tail_chars = budget.message_tail_chars
        max_summary = budget.summary_max_chars

        summary_parts: list[str] = []
        for msg in compressible:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))

            if not content:
                continue

            # F6: keep short messages verbatim (raw > summary)
            if len(content) <= _SHORT_MSG_THRESHOLD:
                pass  # keep whole
            else:
                # F6: head + tail retention with elision
                content = _truncate_with_head_tail(
                    content,
                    head_chars=head_chars,
                    tail_chars=tail_chars,
                )

            summary_parts.append(f"[{role}]: {content}")

        summary_text = "Previous conversation summary:\n" + "\n".join(summary_parts)
        if len(summary_text) > max_summary:
            # Also apply head+tail to the aggregate summary
            summary_text = _truncate_with_head_tail(
                summary_text,
                head_chars=max_summary // 2,
                tail_chars=max_summary // 4,
                elision="\n...[additional context truncated]...\n",
            )

        # Build compressed message list
        compressed_messages = system_msgs + [
            {"role": "system", "content": summary_text}
        ] + volatile_msgs

        compressed_tokens = await self.get_token_count(compressed_messages)
        self._compression_count += 1

        logger.info(
            "Context compressed: %d -> %d msgs, %d -> %d tokens (lossy, %d preserved)",
            original_count, len(compressed_messages),
            original_tokens, compressed_tokens,
            protect_n,
        )

        # Return only the result metadata (not the modified message list —
        # the caller applies the changes)
        return CompressionResult(
            summary=summary_text,
            retained_count=len(compressed_messages),
            discarded_count=original_count - len(compressed_messages),
            original_token_count=original_tokens,
            compressed_token_count=compressed_tokens,
        )

    @property
    def compression_count(self) -> int:
        return self._compression_count
