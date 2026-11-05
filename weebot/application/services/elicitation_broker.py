"""ElicitationBroker: put an MCP server's question to the person, or decline it (H12).

A question needs a live answer while the server's request waits, so only a terminal can
give one: the console approval channel. Every other channel (AUTO mode, cron, webhooks, a
web or chat flow that would have to pause and resume) cannot return typed values into a
request that is still open, and declines (H18e). So does a request outside a tool call, a
form the broker cannot show whole, and a form asking for what looks like a secret: MCP
forms are for non-sensitive input.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from weebot.application.ports.approval_port import ApprovalPort
from weebot.application.ports.mcp_elicitation_port import ElicitationReply, McpElicitationPort
from weebot.application.services.tool_approval import ConsoleApproval, current_approval

logger = logging.getLogger(__name__)

MAX_FIELDS = 10
MAX_MESSAGE_CHARS = 1000
_TYPES = {"string", "number", "integer", "boolean"}
_SECRET_NAME = re.compile(
    r"pass(word|wd|phrase)|secret|token|api[_-]?key|credential|private[_-]?key", re.IGNORECASE
)
DECLINE = ElicitationReply("decline")
CANCEL = ElicitationReply("cancel")


def form_problem(schema: dict[str, Any]) -> str | None:
    """Why the broker will not show *schema*, or None when it can."""
    props = schema.get("properties")
    if schema.get("type") != "object" or not isinstance(props, dict) or not props:
        return "not a flat object form"
    if len(props) > MAX_FIELDS:
        return f"more than {MAX_FIELDS} fields"
    for name, spec in props.items():
        if not isinstance(spec, dict) or spec.get("type") not in _TYPES:
            return f"field {name!r} is not a plain string, number or boolean"
        if _SECRET_NAME.search(name) or spec.get("format") == "password":
            return f"field {name!r} looks like a secret"
    return None


def _coerce(spec: dict[str, Any], text: str) -> Any:
    """The typed value of *text* for a field, or raise ValueError."""
    kind = spec["type"]
    if kind == "boolean":
        if text.lower() in ("y", "yes", "true", "1"):
            return True
        if text.lower() in ("n", "no", "false", "0"):
            return False
        raise ValueError("answer yes or no")
    value: Any = text
    try:
        if kind == "integer":
            value = int(text)
        elif kind == "number":
            value = float(text)
    except ValueError:
        raise ValueError("a whole number" if kind == "integer" else "a number") from None
    options = spec.get("enum")
    if options and value not in options:
        raise ValueError(f"one of: {', '.join(map(str, options))}")
    return value


class ElicitationBroker(McpElicitationPort):
    def __init__(
        self,
        ask: Callable[[str], Awaitable[str]],
        approval: Callable[[], ApprovalPort] = current_approval,
    ) -> None:
        self._ask = ask
        self._approval = approval

    async def elicit(
        self,
        server_name: str,
        message: str,
        schema: dict[str, Any],
        *,
        session_id: str = "",
    ) -> ElicitationReply:
        reason = self._refusal(session_id, schema, message)
        if reason:
            logger.info("elicitation from MCP server %s declined: %s", server_name, reason)
            return DECLINE
        try:
            reply = await self._prompt(server_name, message, schema)
        except (EOFError, KeyboardInterrupt):
            reply = CANCEL
        logger.info("elicitation from MCP server %s: %s", server_name, reply.action)
        return reply

    def _refusal(self, session_id: str, schema: dict[str, Any], message: str) -> str | None:
        if not session_id:
            return "outside a tool call"
        if not isinstance(self._approval(), ConsoleApproval):
            return "no terminal to answer on"
        if len(message) > MAX_MESSAGE_CHARS:
            return "message too long to show whole"
        return form_problem(schema)

    async def _prompt(
        self, server_name: str, message: str, schema: dict[str, Any]
    ) -> ElicitationReply:
        # The server wrote the text, so say who is asking.
        head = f"\nMCP server '{server_name}' asks: {message}\nAnswer it? [y]es / [n]o / [c]ancel: "
        answer = (await self._ask(head)).strip().lower()
        if answer not in ("y", "yes"):
            return CANCEL if answer in ("c", "cancel") else DECLINE
        required = set(schema.get("required") or ())
        content: dict[str, Any] = {}
        for name, spec in schema["properties"].items():
            label = spec.get("title") or name
            hint = f" ({', '.join(map(str, spec['enum']))})" if spec.get("enum") else ""
            error = ""
            while True:
                text = (await self._ask(f"  {error}{label}{hint}: ")).strip()
                if not text:
                    if name in required:
                        return CANCEL
                    break
                try:
                    content[name] = _coerce(spec, text)
                    break
                except ValueError as exc:
                    error = f"({exc}) "
        return ElicitationReply("accept", content)
