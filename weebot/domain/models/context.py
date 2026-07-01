"""Context engine domain models — message tiers, compression, and budgets.

Defines the types used by the pluggable context engine to manage LLM
message context across long sessions.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MessageTier(str, Enum):
    """Stability tier of a message in the context window.

    System messages are always preserved (system prompt, rules).
    Context messages are semi-stable (skill context, tool descriptions).
    Volatile messages are the most recent turns and are compressed first.
    """
    SYSTEM = "system"
    CONTEXT = "context"
    VOLATILE = "volatile"


class CompressionStrategy(str, Enum):
    """Available compression strategies."""
    LOSSY_SUMMARIZE = "lossy_summarize"
    DROP_OLDEST = "drop_oldest"
    DROP_LOW_IMPORTANCE = "drop_low_importance"


class CompressionResult(BaseModel):
    """Result of a context compression operation."""
    summary: str = Field(default="", description="Compressed summary of discarded messages")
    retained_count: int = Field(default=0, description="Number of messages retained")
    discarded_count: int = Field(default=0, description="Number of messages discarded/dropped")
    original_token_count: int = Field(default=0, description="Token count before compression")
    compressed_token_count: int = Field(default=0, description="Token count after compression")


class ContextBudget(BaseModel):
    """Budget configuration for context window management."""
    max_tokens: int = Field(default=12000, ge=1000, description="Maximum allowed tokens")
    protect_last_n: int = Field(default=6, ge=0, description="Keep last N messages untouched")
    target_ratio: float = Field(default=0.5, ge=0.1, le=1.0, description="Target compression ratio")
    strategy: CompressionStrategy = Field(default=CompressionStrategy.LOSSY_SUMMARIZE)

    # ── Phase 4 (F6): Lossy compression caps ────────────────────────
    message_head_chars: int = Field(
        default=120, ge=20, le=1000,
        description="Keep this many chars from the start of a long message (F6).",
    )
    message_tail_chars: int = Field(
        default=120, ge=0, le=1000,
        description="Keep this many chars from the end of a long message (F6).",
    )
    summary_max_chars: int = Field(
        default=2000, ge=200, le=50000,
        description="Max chars for the aggregated summary preamble (F6).",
    )
