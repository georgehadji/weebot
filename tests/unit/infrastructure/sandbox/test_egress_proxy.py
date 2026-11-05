"""H23: the sandbox reaches only the hosts a call was cleared for, through a CONNECT proxy."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import types

from weebot.application.ports.sandbox_port import (
    SandboxConfig,
    network_cleared_for_call,
    network_hosts,
)
from weebot.core.egress_guard import EgressGuard
from weebot.infrastructure.sandbox import egress_proxy, egress_sidecar
from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox
from weebot.infrastructure.sandbox.egress_sidecar import NETWORK, EgressProxyError, EgressSidecar

SECRET = "control-secret"


@contextlib.asynccontextmanager
async def _running(upstream_port: int | None = None, allow_private: bool = True):
    ports = frozenset({80, 443, upstream_port} - {None})
    proxy = egress_proxy.EgressProxy(SECRET, allow_private=allow_private, ports=ports)
    proxy_port, control_port = await proxy.start("127.0.0.1", 0, 0)
    try:
        yield proxy, proxy_port, control_port
    finally:
        await proxy.stop()


async def _echo_server():
    async def handle(reader, writer):
        writer.write(b"echo:" + await reader.read(100))
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def _connect(proxy_port: int, target: str, token: str | None = "t1"):
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    auth = ""
    if token is not None:
        auth = "Proxy-Authorization: Basic " + base64.b64encode(f"{token}:x".encode()).decode()
        auth += "\r\n"
    writer.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n{auth}\r\n".encode())
    status = (await reader.readuntil(b"\r\n")).decode()
    return status, reader, writer


async def _control(port: int, path: str, payload: dict, secret: str = SECRET) -> int:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    body = json.dumps(payload).encode()
    head = f"POST {path} HTTP/1.1\r\nAuthorization: Bearer {secret}\r\nContent-Length: {len(body)}"
    writer.write(f"{head}\r\n\r\n".encode() + body)
    status = (await reader.readuntil(b"\r\n")).decode()
    writer.close()
    return int(status.split()[1])


# ── the proxy ──────────────────────────────────────────────────────────────────────────────


async def test_a_cleared_host_is_tunnelled():
    server, up = await _echo_server()
    async with _running(up) as (proxy, port, _):
        proxy.allow("t1", ["127.0.0.1"])
        status, reader, writer = await _connect(port, f"127.0.0.1:{up}")
        await reader.readuntil(b"\r\n")  # the blank line ends the response head
        writer.write(b"hello")
        data = await reader.read(100)
        writer.close()
    server.close()

    assert " 200 " in status and data == b"echo:hello"


async def test_a_host_not_cleared_for_the_call_is_refused():
    async with _running() as (proxy, port, _):
        proxy.allow("t1", ["pypi.org"])
        status, _, writer = await _connect(port, "example.com:443")
        writer.close()

    assert " 403 " in status


async def test_a_missing_or_unknown_token_gets_407():
    async with _running() as (proxy, port, _):
        proxy.allow("t1", ["example.com"])
        none, _, w1 = await _connect(port, "example.com:443", token=None)
        bad, _, w2 = await _connect(port, "example.com:443", token="other")
        w1.close()
        w2.close()

    assert " 407 " in none and " 407 " in bad


async def test_a_port_outside_80_and_443_is_refused():
    async with _running() as (proxy, port, _):
        proxy.allow("t1", ["example.com"])
        status, _, writer = await _connect(port, "example.com:25")
        writer.close()

    assert " 403 " in status


async def test_only_connect_is_accepted():
    async with _running() as (proxy, port, _):
        proxy.allow("t1", ["example.com"])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        token = base64.b64encode(b"t1:x").decode()
        request = f"GET http://example.com/ HTTP/1.1\r\nProxy-Authorization: Basic {token}\r\n\r\n"
        writer.write(request.encode())
        status = (await reader.readuntil(b"\r\n")).decode()
        writer.close()

    assert " 405 " in status


async def test_an_allowed_name_that_resolves_inside_is_refused():
    async with _running(allow_private=False) as (proxy, port, _):
        proxy.allow("t1", ["localhost"])
        status, _, writer = await _connect(port, "localhost:443")
        writer.close()

    assert " 403 " in status and "private" in status


async def test_a_revoked_token_stops_working():
    async with _running() as (proxy, port, control):
        assert await _control(control, "/allow", {"token": "t1", "hosts": ["example.com"]}) == 200
        assert await _control(control, "/revoke", {"token": "t1"}) == 200
        status, _, writer = await _connect(port, "example.com:443")
        writer.close()

    assert " 407 " in status


async def test_the_control_port_needs_the_secret():
    async with _running() as (proxy, _, control):
        wrong = await _control(control, "/allow", {"token": "t", "hosts": []}, secret="guess")

        assert wrong == 401
        assert proxy._tokens == {}


async def test_a_registry_install_also_reaches_its_file_host():
    async with _running() as (proxy, _, _):
        proxy.allow("t1", ["pypi.org"])

        assert "files.pythonhosted.org" in proxy._tokens["t1"]


# ── the sidecar ────────────────────────────────────────────────────────────────────────────


class _FakeDocker(EgressSidecar):
    def __init__(self):
        super().__init__("docker", "weebot-tool-env:latest")
        self.calls: list[tuple[str, ...]] = []
        self.posts: list[tuple[str, dict]] = []
        self.network_exists = False

    async def _run(self, *args):
        self.calls.append(args)
        if args[:2] == ("network", "inspect") and not self.network_exists:
            raise EgressProxyError("no such network")
        if args[0] == "port":
            return "127.0.0.1:49153"
        if args[0] == "inspect":
            return "true"
        return ""

    async def _wait_ready(self):
        return None

    def _post(self, path, payload):
        self.posts.append((path, payload))


async def test_the_sidecar_makes_an_internal_network_and_a_locked_down_container():
    docker = _FakeDocker()

    async with docker.lease(frozenset({"pypi.org"})) as env:
        pass

    assert ("network", "create", "--internal", NETWORK) in docker.calls
    run = next(c for c in docker.calls if c[0] == "run")
    for flag in ("--read-only", "--cap-drop", "no-new-privileges", "127.0.0.1::3129"):
        assert flag in run
    assert any(c[:3] == ("network", "connect", "--alias") for c in docker.calls)
    assert env["HTTPS_PROXY"].endswith("@egress:3128") and env["NO_PROXY"] == ""


async def test_a_lease_pushes_the_hosts_and_revokes_them_after_the_call():
    docker = _FakeDocker()

    async with docker.lease(frozenset({"b.com", "a.com"})):
        assert [p for p, _ in docker.posts] == ["/allow"]

    assert [p for p, _ in docker.posts] == ["/allow", "/revoke"]
    assert docker.posts[0][1]["hosts"] == ["a.com", "b.com"]
    assert docker.posts[0][1]["token"] == docker.posts[1][1]["token"]


async def test_the_second_lease_reuses_the_running_container():
    docker = _FakeDocker()
    docker.network_exists = True

    async with docker.lease(frozenset({"a.com"})):
        pass
    async with docker.lease(frozenset({"a.com"})):
        pass

    assert [c[0] for c in docker.calls].count("run") == 1


# ── the sandbox ────────────────────────────────────────────────────────────────────────────


def _sandbox(monkeypatch, proxy_on: bool) -> DockerLinuxSandbox:
    settings = types.SimpleNamespace(sandbox_egress_proxy=proxy_on, sandbox_egress_proxy_image=None)
    monkeypatch.setattr("weebot.config.settings.get_settings", lambda: settings)

    async def image():
        return "weebot-tool-env:latest"

    sandbox = DockerLinuxSandbox(SandboxConfig(), docker_path="docker")
    monkeypatch.setattr(sandbox, "_resolve_image", image)
    return sandbox


async def test_no_clearance_means_no_network(monkeypatch):
    sandbox = _sandbox(monkeypatch, proxy_on=True)

    cmd = await sandbox._build_docker_command(["true"])

    assert cmd[cmd.index("--network") + 1] == "none"
    assert sandbox._egress_hosts() is None


async def test_a_cleared_call_with_hosts_runs_on_the_internal_network(monkeypatch):
    sandbox = _sandbox(monkeypatch, proxy_on=True)

    with network_cleared_for_call(frozenset({"pypi.org"})):
        hosts = sandbox._egress_hosts()
    cmd = await sandbox._build_docker_command(["true"], proxied=True)

    assert hosts == frozenset({"pypi.org"})
    assert cmd[cmd.index("--network") + 1] == NETWORK


async def test_with_the_proxy_off_a_cleared_call_keeps_the_old_behaviour(monkeypatch):
    sandbox = _sandbox(monkeypatch, proxy_on=False)

    with network_cleared_for_call(frozenset({"pypi.org"})):
        hosts = sandbox._egress_hosts()
        cmd = await sandbox._build_docker_command(["true"])

    assert hosts is None and "--network" not in cmd


async def test_a_proxy_that_cannot_start_runs_nothing(monkeypatch):
    sandbox = _sandbox(monkeypatch, proxy_on=True)

    async def available():
        return True

    class Broken:
        def lease(self, hosts):
            raise EgressProxyError("no docker network")

    monkeypatch.setattr(sandbox, "is_available", available)
    monkeypatch.setattr(sandbox, "_sidecar", lambda: Broken())

    with network_cleared_for_call(frozenset({"pypi.org"})):
        result = await sandbox.execute(["curl", "https://pypi.org"])

    assert result.returncode == -1 and "call not run" in result.stderr


# ── clearing ───────────────────────────────────────────────────────────────────────────────


def test_the_cleared_call_carries_its_hosts_and_resets():
    assert network_hosts() is None
    with network_cleared_for_call(frozenset({"a.com"})):
        assert network_hosts() == frozenset({"a.com"})
    assert network_hosts() is None


def test_every_host_a_shell_call_names_is_cleared_not_just_one():
    guard = EgressGuard()
    command = "curl https://a.example.org/x && pip install foo"

    hosts = guard.network_hosts("bash_execute", {"command": command})

    assert hosts == frozenset({"a.example.org", "pypi.org"})
    assert guard.network_hosts("bash_execute", {"command": "ls"}) is None
    assert guard.network_hosts("file_read", {"path": "x"}) is None


def test_the_proxy_module_needs_nothing_outside_the_standard_library():
    import ast
    import sys
    from pathlib import Path

    tree = ast.parse(Path(egress_proxy.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])

    assert imported <= set(sys.stdlib_module_names) | {"__future__"}
    assert egress_sidecar.egress_proxy is egress_proxy
