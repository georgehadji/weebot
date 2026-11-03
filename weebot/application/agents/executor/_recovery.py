"""Recovery runner: act on a spent cascade whose cause the ladder can fix (H3).

The cascade raises ``RecoverableLLMError`` when every model failed for a reason the executor
owns (context too long, images refused, a short rate limit). ``core.recovery_ladder`` picks
the rung; this module performs it against the conversation buffer and retries the call.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from weebot.core.error_classifier import ErrorCategory, ErrorClassifier, RecoveryAction
from weebot.core.recovery_ladder import (
    RECOVERABLE,
    RecoveryAttempt,
    Rung,
    failure_message,
    plan_recovery,
)
from weebot.domain.exceptions import AllModelsTrippedError, RecoverableLLMError

if TYPE_CHECKING:
    from weebot.application.agents.executor._base import ExecutorAgent
    from weebot.domain.models.llm_response import LLMResponse

logger = logging.getLogger(__name__)

# Most specific first: an overflow anywhere in the cascade decides what to do, even if
# other models timed out.
_PRIORITY = (
    ErrorCategory.PAYLOAD_TOO_LARGE,
    ErrorCategory.CONTEXT_LENGTH,
    ErrorCategory.MULTIMODAL_UNSUPPORTED,
    ErrorCategory.TOOL_SCHEMA_REJECTED,
    ErrorCategory.QUOTA_EXHAUSTED,
    ErrorCategory.RATE_LIMIT_UPSTREAM,
)
_RETRY_AFTER = re.compile(r"retry.?after\D{0,3}(\d+(?:\.\d+)?)", re.IGNORECASE)
_KEEP_TOOL_OUTPUTS = 4
_BACKOFF_CAP_S = 5.0


def terminal_error(first_error: dict[str, str], default_message: str) -> AllModelsTrippedError:
    """The error the cascade raises when nothing answered, typed by its likely cause."""
    found: dict[ErrorCategory, str] = {}
    for text in first_error.values():
        if text:
            found.setdefault(ErrorClassifier.classify(RuntimeError(text)), text)
    for category in _PRIORITY:
        if category in found:
            match = _RETRY_AFTER.search(found[category])
            return RecoverableLLMError(
                failure_message(category),
                category=category.value,
                retry_after=float(match.group(1)) if match else None,
            )
    return AllModelsTrippedError(default_message)


def strip_media(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Replace image blocks with a text placeholder. Returns the new list and how many."""
    out, count = [], 0
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            out.append(msg)
            continue
        blocks = []
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("image", "image_url"):
                count += 1
                block = {"type": "text", "text": f"[image omitted: {count}]"}
            blocks.append(block)
        out.append({**msg, "content": blocks})
    return out, count


def prune_tool_outputs(
    messages: list[dict[str, Any]], keep_last: int = _KEEP_TOOL_OUTPUTS
) -> tuple[list[dict[str, Any]], int]:
    """Blank all but the last *keep_last* tool outputs. Returns the new list and how many."""
    idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    doomed = set(idx[:-keep_last] if keep_last else idx)
    out = [
        {**m, "content": "[tool output pruned to fit the context window]"} if i in doomed else m
        for i, m in enumerate(messages)
    ]
    return out, len(doomed)


def _replace_buffer(executor: ExecutorAgent, messages: list[dict[str, Any]]) -> None:
    executor._conversation_buffer.clear()
    executor._conversation_buffer.extend(messages)


async def _perform(executor: ExecutorAgent, rung: Rung, exc: RecoverableLLMError) -> bool:
    """Carry out *rung*. False when it did nothing, so the next rung is tried."""
    action = rung.action
    if action is RecoveryAction.COMPRESS:
        changed = False
        if rung.aggressive:
            pruned, n = prune_tool_outputs(list(executor._conversation_buffer))
            if n:
                _replace_buffer(executor, pruned)
                changed = True
        return await executor._context_compressor.force_compress() or changed
    if action is RecoveryAction.STRIP_MEDIA:
        stripped, n = strip_media(list(executor._conversation_buffer))
        if n:
            _replace_buffer(executor, stripped)
        return bool(n)
    if action is RecoveryAction.BACKOFF:
        await asyncio.sleep(min(exc.retry_after or 1.0, _BACKOFF_CAP_S))
        return True
    # FALLBACK_MODEL: the cascade already tried every model it has. LARGER_CONTEXT_MODEL:
    # needs a catalog lookup that is not wired yet (plan H3 follow-up).
    return False


async def call_with_recovery(
    executor: ExecutorAgent,
    messages: list[dict[str, Any]],
    description: str,
    rebuild: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> tuple[LLMResponse, list[dict[str, Any]]]:
    """``call_with_cascade`` with the recovery ladder around it.

    *rebuild* re-assembles the request messages from the (now smaller) conversation buffer.
    Returns the response and the messages that produced it.
    """
    attempt = RecoveryAttempt()
    while True:
        try:
            response = await executor._cascade.call_with_cascade(
                messages, description=description
            )
            return response, messages
        except RecoverableLLMError as exc:
            category = ErrorCategory(exc.category)
            if category not in RECOVERABLE:
                raise
            attempt = RecoveryAttempt(attempt.rungs_used, exc.retry_after)
            while (rung := plan_recovery(category, attempt)) is not None:
                attempt = RecoveryAttempt(attempt.rungs_used | {rung}, exc.retry_after)
                if await _perform(executor, rung, exc):
                    logger.warning("LLM recovery: %s for %s", rung.action.value, category.value)
                    messages = await rebuild()
                    break
            else:
                raise
