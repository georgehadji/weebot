"""LspManager (H20): one language-server process per (workspace root, language), LRU 3.

A server runs the project's own config, so one starts only for a path under the workspace root
or a root named in ``WEEBOT_LSP_TRUSTED_ROOTS``. A language with no server on PATH, a root that
is not trusted, and a server that fails to start all answer "no diagnostics", never an error.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from weebot.application.ports.lsp_port import LspPort
from weebot.config.lsp_servers import LANGUAGES, SERVERS
from weebot.config.secret_accessor import SecretAccessor
from weebot.core.child_env import build_child_env
from weebot.domain.models.diagnostic import Diagnostic
from weebot.infrastructure.lsp.client import LspClient

logger = logging.getLogger(__name__)

MAX_SERVERS = 3


class LspManager(LspPort):
    def __init__(
        self,
        workspace_root: Path,
        trusted_roots: Sequence[Path] = (),
        servers: Mapping[str, Sequence[Sequence[str]]] = SERVERS,
        which: Callable[[str], str | None] = shutil.which,
        max_servers: int = MAX_SERVERS,
    ) -> None:
        self._roots = [workspace_root.resolve(), *(r.resolve() for r in trusted_roots)]
        self._servers = servers
        self._which = which
        self._max = max_servers
        self._clients: OrderedDict[tuple[Path, str], LspClient] = OrderedDict()
        self._failed: set[tuple[Path, str]] = set()
        self._lock = asyncio.Lock()

    def trusted_root(self, path: Path) -> Path | None:
        resolved = path.resolve()
        return next((r for r in self._roots if resolved.is_relative_to(r)), None)

    async def open(self, path: str, text: str) -> None:
        target = Path(path)
        found = await self._client_for(target, spawn=True)
        if found is not None and not found[0].is_open(target):
            await found[0].sync(target, found[1], text)

    async def change(self, path: str, text: str) -> None:
        target = Path(path)
        found = await self._client_for(target, spawn=True)
        if found is not None:
            await found[0].sync(target, found[1], text)

    async def diagnostics(self, path: str, timeout: float) -> list[Diagnostic] | None:
        target = Path(path)
        found = await self._client_for(target, spawn=False)
        if found is None:
            return []
        return await found[0].wait_diagnostics(target, timeout)

    async def close_all(self) -> None:
        async with self._lock:
            clients, self._clients = list(self._clients.values()), OrderedDict()
        for client in clients:
            await client.close()

    async def _client_for(self, path: Path, *, spawn: bool) -> tuple[LspClient, str] | None:
        language_pair = LANGUAGES.get(path.suffix.lower())
        root = self.trusted_root(path)
        if language_pair is None or root is None:
            return None
        language, language_id = language_pair
        key = (root, language)
        async with self._lock:
            client = self._clients.get(key)
            if client is not None and client.alive:
                self._clients.move_to_end(key)
                return client, language_id
            if not spawn or key in self._failed:
                return None
            client = await self._spawn(key)
            if client is None:
                return None
            self._clients[key] = client
            evicted = [self._clients.popitem(last=False)[1] for _ in self._over_limit()]
        for old in evicted:
            await old.close()
        return client, language_id

    def _over_limit(self) -> range:
        return range(max(len(self._clients) - self._max, 0))

    async def _spawn(self, key: tuple[Path, str]) -> LspClient | None:
        root, language = key
        for candidate in self._servers.get(language, ()):
            exe = self._which(candidate[0])
            if not exe:
                continue
            client = LspClient(
                [exe, *candidate[1:]], root, build_child_env(SecretAccessor.environ_view())
            )
            try:
                await client.start()
            except (OSError, RuntimeError, TimeoutError) as exc:
                logger.warning("language server %s did not start: %s", candidate[0], exc)
                await client.close()
                self._failed.add(key)
                return None
            return client
        self._failed.add(key)
        return None
