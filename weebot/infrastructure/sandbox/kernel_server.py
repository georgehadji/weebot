"""A Python interpreter that keeps its variables between calls (H17).

Runs as a standalone script inside the sandbox, so it imports nothing from ``weebot``.
The host sends one JSON object per line on stdin: ``{"code": str, "max_chars": int}``.
The reply is one JSON line on the original stdout: ``{"stdout", "error", "duration",
"truncated"}``. The first line, ``{"ready": true}``, says the kernel is up.

User code gets no real stdin and a null file descriptor 1, so nothing it prints at the
operating-system level can corrupt the reply line; Python-level output (``print``,
``sys.stderr``) is captured, in order, into ``stdout``.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time
import traceback

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


def main() -> None:
    requests = os.fdopen(os.dup(0), "r", encoding="utf-8", newline="\n")
    replies = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
    sys.stdin = io.StringIO("")

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
