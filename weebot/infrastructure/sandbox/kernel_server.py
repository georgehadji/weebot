"""A Python interpreter that keeps its variables between calls (H17).

Runs as a standalone script inside the sandbox, so it imports nothing from ``weebot``.
The host sends one JSON object per line on stdin: ``{"code": str, "max_chars": int}``.
The reply is one JSON line on the original stdout: ``{"stdout", "error", "duration",
"truncated"}``. The first line, ``{"ready": true}``, says the kernel is up.

While code runs it can call host tools through the ``weebot_tools`` module: each call is a
JSON-RPC 2.0 request ``{"rpc": {...}}`` on the reply stream, answered by one
``{"rpc_result": {...}}`` line on stdin, so a call needs no port and no second channel.

User code gets no real stdin and a null file descriptor 1, so nothing it prints at the
operating-system level can corrupt the reply line; Python-level output (``print``,
``sys.stderr``) is captured, in order, into ``stdout``.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import itertools
import sys
import threading
import time
import traceback
import types

DEFAULT_MAX_CHARS = 200_000


class _Capped(io.StringIO):
    """A buffer that stops growing at ``limit`` characters and remembers it did."""

    def __init__(self, limit: int) -> None:
        super().__init__()
        self._limit = limit
        self._size = 0
        self.truncated = False

    def write(self, text: str) -> int:
        room = self._limit - self._size
        if room <= 0:
            self.truncated = True
            return len(text)
        if len(text) > room:
            text, self.truncated = text[:room], True
        self._size += len(text)
        return super().write(text)


def _run(code: str, scope: dict, max_chars: int) -> dict:
    buffer = _Capped(max_chars)
    error = ""
    started = time.monotonic()
    try:
        compiled = compile(code, "<kernel>", "exec")
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            exec(compiled, scope)  # noqa: S102 - running the model's code is this module's job
    except BaseException as exc:  # SystemExit and KeyboardInterrupt end the call, not the kernel
        # Drop this module's own frame so the traceback starts at the user's code.
        error = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__.tb_next))
    return {
        "stdout": buffer.getvalue(),
        "error": error,
        "duration": round(time.monotonic() - started, 4),
        "truncated": buffer.truncated,
    }


class ToolError(RuntimeError):
    """A tool call that did not succeed. ``output`` holds what the tool printed anyway."""

    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output = output


def _tools_module(requests, replies) -> types.ModuleType:
    """``weebot_tools``: the functions user code calls to reach the host's tools."""
    lock = threading.Lock()
    ids = itertools.count(1)

    def call_tool(name: str, **arguments):
        """Run the host tool *name*; returns its output text or raises ToolError."""
        with lock:  # one request in flight, so the reply on stdin is this call's
            request = {
                "jsonrpc": "2.0",
                "id": next(ids),
                "method": "call_tool",
                "params": {"name": name, "arguments": arguments},
            }
            replies.write(json.dumps({"rpc": request}) + "\n")
            replies.flush()
            line = requests.readline()
        if not line:
            raise ToolError("The host closed the connection.")
        reply = json.loads(line).get("rpc_result", {})
        if "error" in reply:
            raise ToolError(str(reply["error"].get("message", "The tool call failed.")))
        result = reply.get("result", {})
        if result.get("error"):
            raise ToolError(str(result["error"]), str(result.get("output", "")))
        return str(result.get("output", ""))

    module = types.ModuleType("weebot_tools")
    module.ToolError = ToolError
    module.call_tool = call_tool
    module.bash = lambda command, **options: call_tool("bash", command=command, **options)
    module.web_search = lambda query: call_tool("web_search", query=query)
    module.file_view = lambda path: call_tool("file_editor", command="view", path=path)
    module.file_write = lambda path, text: call_tool(
        "file_editor", command="create", path=path, file_text=text
    )
    return module


def main() -> None:
    requests = os.fdopen(os.dup(0), "r", encoding="utf-8", newline="\n")
    replies = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
    sys.stdin = io.StringIO("")

    sys.modules["weebot_tools"] = _tools_module(requests, replies)
    scope: dict = {"__name__": "__main__", "__builtins__": __builtins__}
    replies.write(json.dumps({"ready": True}) + "\n")
    replies.flush()
    for line in requests:
        if not line.strip():
            continue
        request = json.loads(line)
        reply = _run(request["code"], scope, int(request.get("max_chars", DEFAULT_MAX_CHARS)))
        replies.write(json.dumps(reply) + "\n")
        replies.flush()


if __name__ == "__main__":
    main()
