"""LSP delta diagnostics (H20): tell the model what its edit broke, not what was already broken.

``LspDiagnosticsMiddleware`` is an H16 hook around ``file_editor`` writes. Before a write it
records the file's diagnostics; after it, it sends the new text to the language server and
appends only the diagnostics that were not there before. The wait is capped at 1.5 s: an answer
that arrives later is queued and attached to the next tool result. Nothing here ever fails a
tool call.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from pathlib import Path
from typing import Any

from weebot.application.middleware.base import Middleware, ToolCall
from weebot.application.ports.lsp_port import LspPort
from weebot.domain.models.diagnostic import Diagnostic

logger = logging.getLogger(__name__)

WRITE_COMMANDS = frozenset({"create", "str_replace", "insert", "write_large"})
WAIT_S = 1.5
LATE_S = 10.0
MAX_REPORTED = 10
LINE_SLACK = 2  # an old diagnostic that moved this many lines is still the same one


def diagnostic_delta(before: list[Diagnostic], after: list[Diagnostic]) -> list[Diagnostic]:
    """What is in *after* but not in *before*, matching on code, message and line within 2."""
    return [
        d
        for d in after
        if not any(
            b.code == d.code and b.message == d.message and abs(b.line - d.line) <= LINE_SLACK
            for b in before
        )
    ]


async def _read(path: Path) -> str:
    return await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")


def describe(path: str, new: list[Diagnostic]) -> str:
    shown = new[:MAX_REPORTED]
    lines = [f"[new diagnostics in {path}]"]
    for d in shown:
        tag = ", ".join(x for x in (d.code, d.source) if x)
        suffix = f" ({tag})" if tag else ""
        lines.append(f"  line {d.line + 1}: {d.severity} {d.message}{suffix}")
    if len(new) > len(shown):
        lines.append(f"  ... and {len(new) - len(shown)} more")
    return "\n".join(lines)


class LspDiagnosticsMiddleware(Middleware):
    def __init__(self, port: LspPort, workspace: Path) -> None:
        self._port = port
        self._workspace = workspace.resolve()
        self._known: dict[str, list[Diagnostic]] = {}
        self._late: list[str] = []
        self._tasks: set[asyncio.Future[Any]] = set()

    def name(self) -> str:
        return "lsp_diagnostics"

    def _target(self, call: ToolCall) -> Path | None:
        if call.name != "file_editor" or call.arguments.get("command") not in WRITE_COMMANDS:
            return None
        raw = call.arguments.get("path")
        if not isinstance(raw, str) or not raw:
            return None
        path = Path(raw)
        return (path if path.is_absolute() else self._workspace / path).resolve()

    def _display(self, path: Path) -> str:
        if path.is_relative_to(self._workspace):
            return str(path.relative_to(self._workspace))
        return str(path)

    async def before_tool_call(self, call: ToolCall) -> ToolCall:
        target = self._target(call)
        if target is None or str(target) in self._known:
            return call
        key = str(target)
        try:
            if target.is_file():
                await self._port.open(key, await _read(target))
                self._known[key] = await self._port.diagnostics(key, WAIT_S) or []
            else:
                self._known[key] = []
        except Exception as exc:
            logger.warning("LSP baseline for %s failed: %s", target, exc)
        return call

    async def transform_tool_result(self, call: ToolCall, result: Any) -> Any:
        notes, self._late = self._late, []
        target = self._target(call)
        if target is not None and not result.error:
            try:
                note = await self._delta(target)
                if note:
                    notes.append(note)
            except Exception as exc:
                logger.warning("LSP diagnostics for %s failed: %s", target, exc)
        if notes:
            result.output = "\n".join([result.output or "", *notes]).lstrip("\n")
        return result

    async def _delta(self, target: Path) -> str:
        key = str(target)
        await self._port.change(key, await _read(target))
        before = self._known.get(key, [])
        task = asyncio.ensure_future(self._port.diagnostics(key, LATE_S))
        done, _ = await asyncio.wait({task}, timeout=WAIT_S)
        if task in done:
            return self._report(key, before, task.result())
        self._tasks.add(task)
        task.add_done_callback(partial(self._on_late, key, before))
        return ""

    def _report(self, key: str, before: list[Diagnostic], after: list[Diagnostic] | None) -> str:
        if after is None:
            return ""
        self._known[key] = after
        new = diagnostic_delta(before, after)
        return describe(self._display(Path(key)), new) if new else ""

    def _on_late(self, key: str, before: list[Diagnostic], task: asyncio.Future[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled() or task.exception() is not None:
            return
        note = self._report(key, before, task.result())
        if note:
            self._late.append(f"[late diagnostics] {note}")
