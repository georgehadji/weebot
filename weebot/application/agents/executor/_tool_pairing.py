"""Pairing repair for tool-call messages (moved out of `_base.py`, WB-06).

An assistant message whose `tool_calls` are not each answered by a `tool` message is
rejected by every provider, and this repository has produced that state more than once
(a compaction that drops the pair, a middleware that rewrites one side). The function is
long because the rules are, and it moved here unchanged when `execute_step` was split:
it was the only reason the executor module imported anything from `message_utils`.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def sanitize_tool_call_pairing(messages: list[dict]) -> list[dict]:
    """Drop tool/assistant messages whose counterpart is missing.

    The provider contract is symmetric: every ``role="tool"`` message must
    follow an assistant message whose ``tool_calls`` contains its
    ``tool_call_id``, and every advertised ``tool_call`` must be answered.
    Violating either is a 400, not a degraded response.

    Both halves can break here without anyone doing anything wrong. The
    conversation buffer is a bounded deque that evicts from the left, so once
    a step exceeds the window it splits assistant/tool pairs exactly at the
    boundary; ``_maybe_compress`` independently rewrites the middle of the
    buffer wholesale. Sizing the buffer to the tool budget makes eviction
    unlikely, not impossible — a long tool result can still trip compression
    mid-step — so the assembled message list is sanitized before dispatch
    rather than trusting the buffer to stay well-formed.

    Returns a new list; the input is not modified.
    """
    answered: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            answered.add(msg["tool_call_id"])

    offered: set[str] = set()
    result: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            kept = [
                tc for tc in msg["tool_calls"] if isinstance(tc, dict) and tc.get("id") in answered
            ]
            if len(kept) != len(msg["tool_calls"]):
                msg = {**msg, "tool_calls": kept}
                if not kept:
                    # An assistant turn with an empty tool_calls list is
                    # itself invalid; drop the key and keep the prose.
                    msg.pop("tool_calls")
            offered.update(tc["id"] for tc in kept)
            result.append(msg)
            continue
        if role == "tool":
            if msg.get("tool_call_id") not in offered:
                continue  # orphan: its parent assistant turn is gone
            result.append(msg)
            continue
        result.append(msg)
    return result
