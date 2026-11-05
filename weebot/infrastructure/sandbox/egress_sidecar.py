"""The egress proxy's container, its internal network, and a lease per call (H23, step 1).

A sandbox call that was cleared for some hosts runs on ``weebot-sandbox-internal`` (a Docker
``--internal`` network: no route out). Its only neighbour is this sidecar, which is also on the
default bridge and so can reach the internet. The sidecar tunnels CONNECT to the hosts the call's
token allows (see ``egress_proxy``).

``lease(hosts)`` pushes the hosts for one call over the control port, which Docker publishes on
host loopback only and which needs a secret the sandbox never sees, and drops them when the call
ends. Anything that goes wrong raises ``EgressProxyError``; the caller must not fall back to an
open network.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import weebot.infrastructure.sandbox.egress_proxy as egress_proxy

logger = logging.getLogger(__name__)

NETWORK = "weebot-sandbox-internal"
ALIAS = "egress"
LABEL = "org.weebot.role=egress-proxy"
_READY_SECONDS = 15


class EgressProxyError(RuntimeError):
    """The proxy could not be started or reached."""


class EgressSidecar:
    def __init__(self, docker_path: str, image: str) -> None:
        self._docker = docker_path
        self._image = image
        self._secret: str | None = None
        self._name: str | None = None
        self._control_port: int | None = None
        self._lock = asyncio.Lock()

    async def _run(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            self._docker, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise EgressProxyError(f"docker {args[0]} failed: {err.decode(errors='replace')[:200]}")
        return out.decode(errors="replace").strip()

    async def ensure(self) -> None:
        """Start the network and the sidecar once; a later call returns at once."""
        async with self._lock:
            if self._control_port is not None and await self._running():
                return
            await self._start()

    async def _running(self) -> bool:
        try:
            state = await self._run("inspect", "-f", "{{.State.Running}}", self._name or "")
        except EgressProxyError:
            return False
        return state == "true"

    async def _start(self) -> None:
        try:
            await self._run("network", "inspect", NETWORK)
        except EgressProxyError:
            await self._run("network", "create", "--internal", NETWORK)
        self._secret = secrets.token_urlsafe(24)
        self._name = f"weebot-egress-{secrets.token_hex(4)}"
        script = Path(egress_proxy.__file__).resolve()
        await self._run(
            "run", "-d", "--rm", "--name", self._name, "--label", LABEL,
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "1000:1000", "--memory", "128m", "--pids-limit", "64",
            "-e", f"EGRESS_CONTROL_SECRET={self._secret}",
            "-p", f"127.0.0.1::{egress_proxy.CONTROL_PORT}",
            "-v", f"{script}:/egress/egress_proxy.py:ro",
            self._image, "python", "/egress/egress_proxy.py",
        )  # fmt: skip
        try:
            await self._run("network", "connect", "--alias", ALIAS, NETWORK, self._name)
            published = await self._run("port", self._name, f"{egress_proxy.CONTROL_PORT}/tcp")
            self._control_port = int(published.splitlines()[0].rsplit(":", 1)[1])
            await self._wait_ready()
        except (EgressProxyError, ValueError, IndexError) as exc:
            await self.stop()
            raise EgressProxyError(f"egress proxy did not start: {exc}") from None
        logger.info("egress proxy %s ready (control port %s)", self._name, self._control_port)

    async def _wait_ready(self) -> None:
        for _ in range(_READY_SECONDS * 5):
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", self._control_port)
                writer.close()
                return
            except OSError:
                await asyncio.sleep(0.2)
        raise EgressProxyError("control port never opened")

    async def stop(self) -> None:
        name, self._name, self._control_port = self._name, None, None
        if name:
            try:
                await self._run("rm", "-f", name)
            except EgressProxyError:
                logger.warning("egress proxy %s could not be removed", name, exc_info=True)

    def _post(self, path: str, payload: dict) -> None:
        request = urllib.request.Request(  # noqa: S310 - fixed http://127.0.0.1 URL
            f"http://127.0.0.1:{self._control_port}{path}",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self._secret}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5):  # noqa: S310
            pass

    @asynccontextmanager
    async def lease(self, hosts: frozenset[str]) -> AsyncIterator[dict[str, str]]:
        """Proxy environment for one call, valid for *hosts* until the block ends."""
        await self.ensure()
        token = secrets.token_urlsafe(16)
        try:
            await asyncio.to_thread(self._post, "/allow", {"token": token, "hosts": sorted(hosts)})
        except OSError as exc:
            raise EgressProxyError(f"egress proxy control failed: {exc}") from None
        url = f"http://{token}:x@{ALIAS}:{egress_proxy.PROXY_PORT}"
        try:
            yield {
                "HTTP_PROXY": url, "HTTPS_PROXY": url, "http_proxy": url, "https_proxy": url,
                "NO_PROXY": "", "no_proxy": "",
            }  # fmt: skip
        finally:
            try:
                await asyncio.to_thread(self._post, "/revoke", {"token": token})
            except OSError:
                logger.warning("egress token could not be revoked", exc_info=True)
