"""Compression v2 (H9): a pipeline of passes over the middle of the conversation.

The buffer is split once into head, middle and tail. Each pass takes the middle and
returns a smaller one; the pipeline stops as soon as the whole buffer is under target.
Only `SummarizeMiddle` calls a model, and it runs only when the pure passes before it did
not get there. ADR-022 has the reasoning.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from weebot.application.services.context_tokenizer import ContextTokenizer

logger = logging.getLogger(__name__)

Message = dict[str, Any]

KEEP_HEAD = 3
"""Messages kept verbatim at the start: the step prompt that anchors the task."""

PROTECT_LAST_N = 4
"""Messages at the end that are never compressed, whatever the target says."""

TRIGGER_RATIO_SMALL = 0.75
TRIGGER_RATIO_LARGE = 0.50
LARGE_WINDOW = 512_000
TAIL_RATIO = 0.20
TARGET_RATIO = 0.35
"""Share of the window the whole buffer should fall to after compression."""

MIN_PRUNE_CHARS = 200
"""A result shorter than this costs less than its own stub."""

_SPILL_PATH = re.compile(r"\[full output: (?P<path>.+?), \d+ chars")

_tokens = ContextTokenizer().estimate_messages_tokens


@dataclass(frozen=True, slots=True)
class TokenBudget:
    """Every number the pipeline needs, derived from one model's window."""

    window: int

    @property
    def trigger_tokens(self) -> int:
        ratio = TRIGGER_RATIO_SMALL if self.window < LARGE_WINDOW else TRIGGER_RATIO_LARGE
        return int(self.window * ratio)

    @property
    def tail_tokens(self) -> int:
        return int(self.window * TAIL_RATIO)

    @property
    def target_tokens(self) -> int:
        return int(self.window * TARGET_RATIO)


class CompressionPass(Protocol):
    name: str

    async def apply(self, middle: Sequence[Message], budget: TokenBudget) -> list[Message]: ...


# ── splitting ───────────────────────────────────────────────────────────────


def select_tail(
    msgs: Sequence[Message], target_tokens: int, protect_last_n: int = PROTECT_LAST_N
) -> int:
    """Index where the protected tail starts.

    Walks backwards until `target_tokens` is spent, never keeping fewer than
    `protect_last_n` messages, then moves the start back so a tool result is never
    separated from the assistant message that called it.
    """
    start, spent = len(msgs), 0
    while start > 0:
        spent += _tokens([msgs[start - 1]])
        if spent > target_tokens and len(msgs) - start >= protect_last_n:
            break
        start -= 1
    while 0 < start < len(msgs) and msgs[start].get("role") == "tool":
        start -= 1
    return start


def _head_end(msgs: Sequence[Message], keep: int = KEEP_HEAD) -> int:
    """End of the head, extended over the tool results of a call it contains."""
    end = min(keep, len(msgs))
    while end < len(msgs) and msgs[end].get("role") == "tool":
        end += 1
    return end


# ── passes ──────────────────────────────────────────────────────────────────


def _tool_names(middle: Sequence[Message]) -> dict[str, str]:
    return {
        tc["id"]: (tc.get("function") or {}).get("name", "tool")
        for m in middle
        for tc in (m.get("tool_calls") or [])
        if isinstance(tc, dict) and tc.get("id")
    }


def _is_big_result(m: Message) -> bool:
    c = m.get("content")
    return m.get("role") == "tool" and isinstance(c, str) and len(c) >= MIN_PRUNE_CHARS


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()


class PruneOldToolOutputs:
    """Replace each large tool result with a one-line stub (no model call)."""

    name = "prune_old_tool_outputs"

    async def apply(self, middle: Sequence[Message], budget: TokenBudget) -> list[Message]:
        names = _tool_names(middle)
        out: list[Message] = []
        for m in middle:
            if not _is_big_result(m):
                out.append(m)
                continue
            content = m["content"]
            spill = _SPILL_PATH.search(content)
            where = f"; spill: {spill['path']}" if spill else ""
            tool = names.get(m.get("tool_call_id", ""), "tool")
            out.append(
                {**m, "content": f"[tool output pruned: {tool}, {len(content)} chars{where}]"}
            )
        return out


class DedupeResults:
    """Keep only the last copy of an identical tool result (no model call)."""

    name = "dedupe_results"

    async def apply(self, middle: Sequence[Message], budget: TokenBudget) -> list[Message]:
        last = {_digest(m["content"]): i for i, m in enumerate(middle) if _is_big_result(m)}
        return [
            {**m, "content": "[duplicate of a later result]"}
            if _is_big_result(m) and last[_digest(m["content"])] != i
            else m
            for i, m in enumerate(middle)
        ]


def _summary_message(count: int, text: str) -> Message:
    # User role: a mid-buffer system message is rejected by Anthropic and breaks prefix caching.
    return {"role": "user", "content": f"[Context summary — {count} turns compressed]\n{text}"}


def _is_summary(middle: Sequence[Message]) -> bool:
    return len(middle) == 1 and str(middle[0].get("content", "")).startswith("[Context summary")


class SummarizeMiddle:
    """Replace the middle with one model-written summary. The only pass that does I/O."""

    name = "summarize_middle"

    def __init__(self, summarize: Callable[[Sequence[Message]], Awaitable[str]]) -> None:
        self._summarize = summarize

    async def apply(self, middle: Sequence[Message], budget: TokenBudget) -> list[Message]:
        if not middle:
            return list(middle)
        text = await self._summarize(middle)
        return [_summary_message(len(middle), text)] if text else list(middle)


class DeterministicFallback:
    """If nothing summarized the middle, drop it and say which tools it used."""

    name = "deterministic_fallback"

    async def apply(self, middle: Sequence[Message], budget: TokenBudget) -> list[Message]:
        if not middle or _is_summary(middle):
            return list(middle)
        used = sorted(set(_tool_names(middle).values()))
        listed = f" Tools used: {', '.join(used)}." if used else ""
        return [_summary_message(len(middle), f"(not summarized; the turns were dropped.{listed})")]


def default_passes(
    summarize: Callable[[Sequence[Message]], Awaitable[str]],
) -> tuple[CompressionPass, ...]:
    """Order is data: a new step is one more entry."""
    return (
        PruneOldToolOutputs(),
        DedupeResults(),
        SummarizeMiddle(summarize),
        DeterministicFallback(),
    )


# ── pipeline ────────────────────────────────────────────────────────────────


async def compress_messages(
    msgs: Sequence[Message], budget: TokenBudget, passes: Sequence[CompressionPass]
) -> list[Message]:
    """Return `msgs` compressed to `budget.target_tokens`, or unchanged if already there."""
    msgs = list(msgs)
    head_end = _head_end(msgs)
    tail_start = select_tail(msgs, budget.tail_tokens)
    if tail_start <= head_end:
        return msgs
    head, middle, tail = msgs[:head_end], msgs[head_end:tail_start], msgs[tail_start:]

    for p in passes:
        if _tokens(head + middle + tail) <= budget.target_tokens:
            break
        try:
            middle = list(await p.apply(middle, budget))
        except Exception as exc:  # one failing pass must not cost the caller its buffer
            logger.warning("Compression pass %s failed: %s: %s", p.name, type(exc).__name__, exc)
    return head + middle + tail
