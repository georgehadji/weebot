"""Encode and rebuild bus events as JSON, for the Valkey bridge.

Agent events are rebuilt through the AgentEvent union (each has a Literal
``type``); domain events through a registry of DomainEvent subclasses keyed by
their ``type`` default, which their plain ``str`` type field cannot provide.
Fields typed ``Any`` (a plan, a tool artifact) come back as plain dicts.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import TypeAdapter

from weebot.domain.models.event import AgentEvent, DomainEvent

logger = logging.getLogger(__name__)

_AGENT = TypeAdapter(AgentEvent)


def _subclasses(cls: type) -> list[type]:
    found = []
    for sub in cls.__subclasses__():
        found.append(sub)
        found.extend(_subclasses(sub))
    return found


_DOMAIN_TYPES: dict[str, type[DomainEvent]] = {
    cls.model_fields["type"].default: cls
    for cls in _subclasses(DomainEvent)
    if cls.model_fields["type"].default
}


def encode(event: Any) -> dict[str, Any]:
    """The wire form of *event*: its kind and its JSON-safe fields."""
    kind = "domain" if isinstance(event, DomainEvent) else "agent"
    return {"kind": kind, "data": event.model_dump(mode="json")}


def decode(payload: dict[str, Any]) -> Any | None:
    """Rebuild an event from :func:`encode`'s output; None when it cannot be."""
    try:
        data = payload["data"]
        if payload.get("kind") == "domain":
            cls = _DOMAIN_TYPES.get(data.get("type", ""))
            return cls.model_validate(data) if cls is not None else None
        return _AGENT.validate_python(data)
    except Exception:
        logger.warning("Could not rebuild a bridged event", exc_info=True)
        return None


def dumps(origin: str, event: Any) -> str:
    """A channel message: the sender's origin id and the encoded event."""
    return json.dumps({"origin": origin, "event": encode(event)})


def loads(message: str) -> tuple[str, Any | None]:
    """``(origin, event)`` from a channel message; event None when unreadable."""
    try:
        body = json.loads(message)
        return body.get("origin", ""), decode(body["event"])
    except Exception:
        logger.warning("Unreadable bridged event message", exc_info=True)
        return "", None
