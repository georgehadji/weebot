"""Lossy Context Compressor — default context engine implementation.

Implements IContextEnginePort by summarizing older messages into a
compressed preamble while preserving the last N messages as-is.
"""
from __future__ import annotations

import logging
from typing import Any

from weebot.application.ports.context_engine_port import IContextEnginePort
from weebot.domain.models.context import (
    CompressionResult,
    CompressionStrategy,
    ContextBudget,
)

logger = logging.getLogger(__name__)


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
        summary_parts: list[str] = []
        for msg in compressible:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))
            if content and len(content) > 150:
                content = content[:150] + "..."
            if content:
                summary_parts.append(f"[{role}]: {content}")

        summary_text = "Previous conversation summary:\n" + "\n".join(summary_parts)
        if len(summary_text) > 2000:
            summary_text = summary_text[:2000] + "\n[additional context truncated]"

        # Build compressed message list
        compressed_messages = system_msgs + [
            {"role": "system", "content": summary_text}
        ] + volatile_msgs

        compressed_tokens = await self.get_token_count(compressed_messages)
        self._compression_count += 1

        logger.info(
            "Context compressed: %d → %d msgs, %d → %d tokens (lossy, %d preserved)",
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
