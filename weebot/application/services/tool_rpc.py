"""The host side of the tool calls a kernel's code makes (H17, PR 2).

Code running in a persistent kernel calls ``weebot_tools.bash(...)`` and the like. Each call
reaches ``ToolRpcServer.handle`` as a JSON-RPC 2.0 frame and is dispatched through
``ToolExecutor.execute_tool``, so the guard chain, the approval floors (H18), the egress
gate, taint, coercion and the effect ledger apply to it exactly as to a call the model made.

A tool call from the kernel that pauses for approval is not paused: the code gets an error
saying so, and the model can make the call itself, where the approval prompt can reach a
person.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from weebot.domain.models.tool_result import ToolResult

logger = logging.getLogger(__name__)

ToolDispatch = Callable[[str, dict[str, Any]], Awaitable[ToolResult]]

MAX_CALLS_PER_EXEC = 24  # the per-step tool-call cap (GuardConfig.max_tool_calls_per_step)
MAX_REPLY_CHARS = 200_000
NEVER_ALLOWED = frozenset({"dispatch_parallel_tasks", "python_execute"})

_METHOD_NOT_FOUND, _INVALID_PARAMS, _NOT_ALLOWED, _CAP_REACHED = -32601, -32602, -32001, -32002

_dispatch_var: ContextVar[ToolDispatch | None] = ContextVar("tool_rpc_dispatch", default=None)


@contextmanager
def tool_rpc_scope(dispatch: ToolDispatch) -> Iterator[None]:
    """Let the ``python_execute`` call running in this block reach tools through *dispatch*."""
    token = _dispatch_var.set(dispatch)
    try:
        yield
    finally:
        _dispatch_var.reset(token)


def current_dispatch() -> ToolDispatch | None:
    return _dispatch_var.get()


def parse_allowed(names: str | Iterable[str]) -> frozenset[str]:
    """``"bash, file_editor"`` -> {"bash", "file_editor"}. Dispatch tools are never allowed."""
    items = names.split(",") if isinstance(names, str) else names
    return frozenset(n.strip() for n in items if n.strip()) - NEVER_ALLOWED


class ToolRpcServer:
    """Answers the tool calls of one ``exec``; the count of calls is per instance."""

    def __init__(
        self,
        dispatch: ToolDispatch,
        allowed: frozenset[str],
        max_calls: int = MAX_CALLS_PER_EXEC,
    ) -> None:
        self._dispatch = dispatch
        self._allowed = allowed - NEVER_ALLOWED
        self._max_calls = max_calls
        self.calls = 0

    async def handle(self, frame: dict) -> dict:
        ident = frame.get("id")
        if frame.get("method") != "call_tool":
            return _error(ident, _METHOD_NOT_FOUND, "Unknown method; use call_tool.")
        params = frame.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        arguments = params.get("arguments", {}) if isinstance(params, dict) else None
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(ident, _INVALID_PARAMS, "call_tool needs a name and an arguments object.")
        if name not in self._allowed:
            allowed = ", ".join(sorted(self._allowed)) or "none"
            message = f"'{name}' is not available here (allowed: {allowed})."
            return _error(ident, _NOT_ALLOWED, message)
        if self.calls >= self._max_calls:
            return _error(ident, _CAP_REACHED, f"At most {self._max_calls} tool calls per run.")
        self.calls += 1
        try:
            result = await self._dispatch(name, arguments)
        except Exception as exc:
            logger.warning("kernel tool call %s failed: %s", name, exc, exc_info=True)
            return _result(ident, "", f"The tool call failed: {type(exc).__name__}")
        return _result(ident, *_flatten(result))


def _flatten(result: ToolResult) -> tuple[str, str]:
    """(output, error) for the kernel; a pause for approval is an error it can explain."""
    output = str(result.output or "")
    error = str(result.error or "")
    if (result.data or {}).get("approval_required"):
        error = error or "This call needs approval; make it as a tool call, not from code."
    if len(output) > MAX_REPLY_CHARS:
        output = output[:MAX_REPLY_CHARS] + "\n...[output truncated]"
    return output, error


def _result(ident: Any, output: str, error: str) -> dict:
    return {"jsonrpc": "2.0", "id": ident, "result": {"output": output, "error": error}}


def _error(ident: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}
