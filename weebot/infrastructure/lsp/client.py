"""A minimal LSP client over a child process's stdio: JSON-RPC with Content-Length framing.

It speaks only what H20 needs: initialize, didOpen/didChange and the server's pushed
``textDocument/publishDiagnostics``. Requests the server makes of the client (configuration,
capability registration, progress) get a null or empty answer so the server never waits on us.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from weebot.domain.models.diagnostic import Diagnostic

logger = logging.getLogger(__name__)

_SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "hint"}
# The first publish after a change is often the syntax pass; wait this long for the next one.
_SETTLE_S = 0.15


class LspClient:
    def __init__(self, argv: Sequence[str], root: Path, env: dict[str, str]) -> None:
        self._argv = list(argv)
        self._root = root
        self._env = env
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._versions: dict[str, int] = {}
        self._published: dict[str, list[Diagnostic]] = {}
        self._fresh: dict[str, asyncio.Event] = {}

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self._argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=self._root,
            env=self._env,
        )
        self._reader = asyncio.create_task(self._read_loop())
        capabilities = {
            "textDocument": {
                "synchronization": {"didSave": False},
                "publishDiagnostics": {"relatedInformation": False},
            }
        }
        await asyncio.wait_for(
            self._request(
                "initialize",
                {"processId": None, "rootUri": self._root.as_uri(), "capabilities": capabilities},
            ),
            timeout=15,
        )
        await self._notify("initialized", {})

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def sync(self, path: Path, language: str, text: str) -> None:
        """Open *path*, or send *text* as its new content if it is already open."""
        uri = path.as_uri()
        self._fresh[uri] = asyncio.Event()
        if uri not in self._versions:
            self._versions[uri] = 1
            doc = {"uri": uri, "languageId": language, "version": 1, "text": text}
            await self._notify("textDocument/didOpen", {"textDocument": doc})
            return
        self._versions[uri] += 1
        await self._notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": self._versions[uri]},
                "contentChanges": [{"text": text}],
            },
        )

    def is_open(self, path: Path) -> bool:
        return path.as_uri() in self._versions

    async def wait_diagnostics(self, path: Path, timeout: float) -> list[Diagnostic] | None:
        uri = path.as_uri()
        fresh = self._fresh.get(uri)
        if fresh is None:
            return self._published.get(uri, [])
        try:
            await asyncio.wait_for(fresh.wait(), timeout)
        except TimeoutError:
            return None
        await asyncio.sleep(_SETTLE_S)
        return self._published.get(uri, [])

    async def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.returncode is None:
            try:
                await asyncio.wait_for(self._request("shutdown", None), timeout=2)
                await self._notify("exit", None)
            except (TimeoutError, OSError, RuntimeError) as exc:
                logger.debug("LSP shutdown failed (%s); killing %s", exc, self._argv[0])
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
        if self._reader is not None:
            self._reader.cancel()

    # ── JSON-RPC plumbing ────────────────────────────────────────────────────────
    async def _send(self, message: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        body = json.dumps(message).encode()
        self._proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        await self._proc.stdin.drain()

    async def _notify(self, method: str, params: Any) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _request(self, method: str, params: Any) -> Any:
        self._next_id += 1
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[self._next_id] = future
        await self._send(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        )
        return await future

    async def _read_message(self) -> dict[str, Any] | None:
        assert self._proc is not None and self._proc.stdout is not None
        length = 0
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            name, _, value = line.partition(b":")
            if name.lower() == b"content-length":
                length = int(value)
        return json.loads(await self._proc.stdout.readexactly(length))

    async def _read_loop(self) -> None:
        try:
            while (message := await self._read_message()) is not None:
                await self._dispatch(message)
        except (asyncio.IncompleteReadError, ValueError, OSError) as exc:
            logger.warning("LSP stream from %s ended: %s", self._argv[0], exc)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError("language server exited"))

    async def _dispatch(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method is None:
            future = self._pending.pop(message.get("id"), None)
            if future is not None and not future.done():
                future.set_result(message.get("result"))
            return
        if method == "textDocument/publishDiagnostics":
            self._on_publish(message["params"])
        elif "id" in message:
            result: Any = None
            if method == "workspace/configuration":
                result = [None] * len(message["params"].get("items", []))
            await self._send({"jsonrpc": "2.0", "id": message["id"], "result": result})

    def _on_publish(self, params: dict[str, Any]) -> None:
        uri = params["uri"]
        path = _uri_to_path(uri)
        self._published[uri] = [_diagnostic(path, raw) for raw in params.get("diagnostics", [])]
        event = self._fresh.get(uri)
        if event is not None:
            event.set()


def _uri_to_path(uri: str) -> str:
    path = unquote(urlparse(uri).path)
    return path[1:] if len(path) > 2 and path[0] == "/" and path[2] == ":" else path


def _diagnostic(path: str, raw: dict[str, Any]) -> Diagnostic:
    start, end = raw["range"]["start"], raw["range"]["end"]
    return Diagnostic(
        path=path,
        line=start["line"],
        column=start["character"],
        end_line=end["line"],
        end_column=end["character"],
        severity=_SEVERITY.get(raw.get("severity", 1), "error"),
        code=str(raw.get("code", "")),
        message=raw.get("message", ""),
        source=raw.get("source", ""),
    )
