"""Shared event reconstruction utility — converts dict lists back to AgentEvent subtypes.

Extracted from inline ``TypeAdapter`` usage in flow states (planning, executing,
updating) into a single reusable function with consistent error handling.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import TypeAdapter

from weebot.domain.models.event import AgentEvent

logger = logging.getLogger(__name__)

# Lazily-initialised TypeAdapter for the AgentEvent union type.
# Initialised once per process, reused across all reconstruction calls.
_event_adapter: TypeAdapter[AgentEvent] | None = None


def _get_event_adapter() -> TypeAdapter[AgentEvent]:
    """Return the process-wide TypeAdapter for AgentEvent."""
    global _event_adapter
    if _event_adapter is None:
        _event_adapter = TypeAdapter(AgentEvent)
    return _event_adapter


def reconstruct_events(event_dicts: list[dict[str, Any]]) -> list[AgentEvent]:
    """Reconstruct a list of ``AgentEvent`` subtypes from dict representations.

    Uses a process-wide ``TypeAdapter`` to handle the union discriminator
    (``type`` field). Malformed entries are logged and skipped rather than
    aborting the entire list.

    Args:
        event_dicts: List of event dictionaries (as produced by
            ``event.model_dump()``).

    Returns:
        List of validated ``AgentEvent`` instances. Invalid entries
        are logged and omitted.
    """
    adapter = _get_event_adapter()
    events: list[AgentEvent] = []

    for event_dict in event_dicts:
        try:
            event = adapter.validate_python(event_dict)
            events.append(event)
        except Exception:
            logger.warning(
                "reconstruct_events: skipping unparseable event %s",
                str(event_dict)[:200],
            )
            continue

    return events
