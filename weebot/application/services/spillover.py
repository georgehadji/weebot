"""Tool-output spillover (H7): keep the full text on disk, give the model a head and tail.

``ToolCollection`` caps an output at ``MAX_TOOL_OUTPUT_CHARS`` and used to discard the rest.
It now leaves the original in ``metadata["full_output"]``; ``SpilloverMiddleware`` (an H16
``transform_tool_result`` hook) stores it, replaces the output with a head and tail preview that
names the file, and drops the copy. ``spill_over_budget`` applies the per-turn limit.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from weebot.application.middleware.base import Middleware, ToolCall
from weebot.application.ports.spillover_store_port import SpilloverStorePort, SpillRef
from weebot.config.constants import MAX_TOOL_OUTPUT_CHARS, TURN_OUTPUT_BUDGET_CHARS
from weebot.config.secret_accessor import SecretAccessor
from weebot.core.log_context import session_id_var

logger = logging.getLogger(__name__)

ERROR_CAP = 8_000
BUDGET_PREVIEW_CAP = 2_000
_FOOTER_START = "\n[full output: "
_OMITTED_MARKER_ROOM = 40
_HEAD_RATIO = 0.6


def footer(ref: SpillRef) -> str:
    return (
        f"{_FOOTER_START}{ref.path}, {ref.chars} chars — "
        "read with file_editor view view_range=[a,b]]"
    )


def preview(text: str, cap: int, ref: SpillRef) -> str:
    """Head (60%) and tail (40%) of *text*, plus a footer naming the file; at most *cap* chars."""
    tail_note = footer(ref)
    room = max(cap - len(tail_note) - _OMITTED_MARKER_ROOM, 0)
    head_n = int(room * _HEAD_RATIO)
    tail_n = room - head_n
    omitted = max(len(text) - head_n - tail_n, 0)
    tail = text[len(text) - tail_n :] if tail_n else ""
    return f"{text[:head_n]}\n...[{omitted} chars omitted]...\n{tail}{tail_note}"


def shrink(spilled: str, cap: int) -> str:
    """Cut an already-spilled preview down to *cap*, keeping its footer."""
    body, sep, note = spilled.rpartition(_FOOTER_START)
    if not sep:
        return spilled[:cap]
    note = _FOOTER_START + note
    return body[: max(cap - len(note) - 20, 0)] + "\n...[truncated]" + note


def turn_budget() -> int:
    """Characters of tool output a single turn may add before later results spill."""
    raw = SecretAccessor.get("WEEBOT_TURN_OUTPUT_BUDGET")
    try:
        return int(raw) if raw else TURN_OUTPUT_BUDGET_CHARS
    except ValueError:
        logger.warning("WEEBOT_TURN_OUTPUT_BUDGET=%r is not an integer; using the default", raw)
        return TURN_OUTPUT_BUDGET_CHARS


def _call_id(name: str, suffix: str = "") -> str:
    return f"{name}-{uuid.uuid4().hex[:10]}{suffix}"


class SpilloverMiddleware(Middleware):
    def __init__(self, store: SpilloverStorePort) -> None:
        self._store = store

    def name(self) -> str:
        return "spillover"

    async def transform_tool_result(self, call: ToolCall, result: Any) -> Any:
        session = session_id_var.get() or "unknown"
        full = result.metadata.pop("full_output", None)
        if full:
            ref = await self._store.write(session, _call_id(call.name), full)
            result.output = preview(full, MAX_TOOL_OUTPUT_CHARS, ref)
            result.metadata["spill_path"] = ref.path
        error = result.error
        if error and len(error) > ERROR_CAP:
            ref = await self._store.write(session, _call_id(call.name, "-err"), error)
            result.error = preview(error, ERROR_CAP, ref)
            result.metadata["spill_error_path"] = ref.path
        return result


async def spill_over_budget(
    store: SpilloverStorePort,
    session_id: str,
    tool_names: list[str],
    results: list[Any],
    budget: int,
) -> None:
    """Once a turn's outputs add up past *budget*, shrink every later result to a 2 K preview.

    A result that already spilled keeps its file; one that did not is written out first.
    Mutates *results* in place.
    """
    total = 0
    for name, result in zip(tool_names, results, strict=False):
        text = result.output or ""
        total += len(text)
        if total <= budget or len(text) <= BUDGET_PREVIEW_CAP:
            continue
        if result.metadata.get("spill_path"):
            result.output = shrink(text, BUDGET_PREVIEW_CAP)
        else:
            ref = await store.write(session_id, _call_id(name), text)
            result.output = preview(text, BUDGET_PREVIEW_CAP, ref)
            result.metadata["spill_path"] = ref.path
        result.metadata["spilled_for_turn_budget"] = True
