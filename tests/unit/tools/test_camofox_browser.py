"""camofox_browser: a stealth Firefox (Camoufox) for pages that block normal fetches.

camofox-browser (github.com/jo-inc/camofox-browser, MIT) is a REST server. The
tool starts it on 127.0.0.1 with a per-process access key, exposes only
browse/read/click/type, and treats page text as untrusted. JavaScript
evaluation, uploads, cookie import and downloads are not reachable.
"""

from __future__ import annotations

import json

import httpx
import pytest

from weebot.core.egress_guard import EgressGuard
from weebot.core.trust_boundary import is_untrusted_tool, taints_egress_context
from weebot.tools import camofox_browser as cb
from weebot.tools.camofox_browser import CamofoxBrowserTool


@pytest.fixture
def server(monkeypatch):
    """A fake camofox server: records requests, answers like the real one."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/tabs" and request.method == "POST":
            return httpx.Response(200, json={"tabId": "t1", "url": "https://example.com/"})
        if path.endswith("/snapshot"):
            snap = {"url": "https://example.com/", "snapshot": "[link e1] More"}
            return httpx.Response(200, json=snap)
        if path.endswith("/links"):
            links = [{"url": "https://iana.org", "text": "More"}]
            return httpx.Response(200, json={"links": links})
        return httpx.Response(200, json={"ok": True, "url": "https://example.com/"})

    async def _server(config):
        return "http://127.0.0.1:9999", "k"

    monkeypatch.setattr(cb, "_ensure_server", _server)
    monkeypatch.setattr(cb, "_TRANSPORT", httpx.MockTransport(handler))

    async def _public(host):
        return True

    monkeypatch.setattr(cb, "_is_public_host", _public)
    return seen


def test_camofox_is_on_the_trust_boundary():
    assert is_untrusted_tool("camofox_browser") and taints_egress_context("camofox_browser")


async def test_open_returns_the_tab_and_its_snapshot_with_the_access_key(server):
    result = await CamofoxBrowserTool().execute(action="open", url="https://example.com")
    assert not result.is_error, result.error
    assert "t1" in result.output and "[link e1]" in result.output
    assert server[0].headers["authorization"] == "Bearer k"
    assert json.loads(server[0].content)["url"] == "https://example.com"


@pytest.mark.parametrize(
    "kwargs, path",
    [
        ({"action": "snapshot", "tab_id": "t1"}, "/tabs/t1/snapshot"),
        ({"action": "click", "tab_id": "t1", "ref": "e1"}, "/tabs/t1/click"),
        ({"action": "type", "tab_id": "t1", "ref": "e2", "text": "hi"}, "/tabs/t1/type"),
        ({"action": "press", "tab_id": "t1", "key": "Enter"}, "/tabs/t1/press"),
        ({"action": "scroll", "tab_id": "t1", "direction": "down"}, "/tabs/t1/scroll"),
        ({"action": "back", "tab_id": "t1"}, "/tabs/t1/back"),
        ({"action": "links", "tab_id": "t1"}, "/tabs/t1/links"),
        ({"action": "close", "tab_id": "t1"}, "/tabs/t1"),
        (
            {"action": "navigate", "tab_id": "t1", "macro": "@wikipedia_search", "query": "x"},
            "/tabs/t1/navigate",
        ),
    ],
)
async def test_each_action_reaches_its_endpoint(server, kwargs, path):
    result = await CamofoxBrowserTool().execute(**kwargs)
    assert not result.is_error, result.error
    assert server[0].url.path == path


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": "evaluate", "tab_id": "t1", "expression": "document.cookie"},
        {"action": "upload", "tab_id": "t1"},
        {"action": "import_cookies"},
        {"action": "open", "url": "file:///C:/Users/tesse/.env"},
        {"action": "open", "url": "javascript:alert(1)"},
        {"action": "navigate", "tab_id": "t1", "macro": "@linkedin_search", "query": "x"},
        {"action": "click", "tab_id": "../sessions/weebot/cookies", "ref": "e1"},
        {"action": "click", "tab_id": "t1"},
    ],
)
async def test_unsafe_or_malformed_calls_are_refused(server, kwargs):
    result = await CamofoxBrowserTool().execute(**kwargs)
    assert result.is_error
    assert server == []


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:9377/tabs",
        "http://localhost:8000/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
    ],
)
async def test_local_and_private_addresses_are_refused(monkeypatch, url):
    """camofox itself loads loopback URLs (checked live), so the tool must block them."""
    monkeypatch.setattr(cb, "_ensure_server", None)  # never reached
    result = await CamofoxBrowserTool().execute(action="open", url=url)
    assert result.is_error and "private" in result.error


async def test_a_redirect_to_a_private_address_closes_the_tab(monkeypatch, server):
    def handler(request):
        server.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"tabId": "t1", "url": "http://10.0.0.5/admin"})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(cb, "_TRANSPORT", httpx.MockTransport(handler))
    result = await CamofoxBrowserTool().execute(action="open", url="https://example.com")
    assert result.is_error and "private" in result.error
    assert server[-1].method == "DELETE"


async def test_long_snapshots_are_truncated(monkeypatch, server):
    big = "x" * 80_000
    monkeypatch.setattr(
        cb, "_TRANSPORT",
        httpx.MockTransport(lambda r: httpx.Response(200, json={"snapshot": big, "url": "u"})),
    )
    result = await CamofoxBrowserTool().execute(action="snapshot", tab_id="t1")
    assert "truncated" in result.output and len(result.output) < 60_000


async def test_a_server_error_is_reported(monkeypatch, server):
    monkeypatch.setattr(
        cb, "_TRANSPORT",
        httpx.MockTransport(lambda r: httpx.Response(500, json={"error": "tab create timed out"})),
    )
    result = await CamofoxBrowserTool().execute(action="snapshot", tab_id="t1")
    assert result.is_error and "timed out" in result.error


def test_the_server_env_is_local_keyed_and_has_no_weebot_secrets(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")
    monkeypatch.setenv("CAMOFOX_API_KEY", "would-enable-cookie-import")
    env = cb._server_env(port=12345, access_key="abc", admin_key="adm")
    assert "OPENROUTER_API_KEY" not in env and "CAMOFOX_API_KEY" not in env
    assert env["CAMOFOX_BIND_HOST"] == "127.0.0.1"
    assert env["CAMOFOX_PORT"] == "12345" and env["CAMOFOX_ACCESS_KEY"] == "abc"
    assert env["CAMOFOX_CRASH_REPORT_ENABLED"] == "false"
    # The exit hook stops the browser with it: killing node alone orphans Firefox on Windows.
    assert env["CAMOFOX_ADMIN_KEY"] == "adm"
    # Without production, camofox lets loopback callers import cookies unauthenticated.
    assert env["NODE_ENV"] == "production"


def test_shutdown_stops_the_browser_before_killing_node(monkeypatch):
    calls: list[tuple] = []

    class _Proc:
        returncode = None

        def kill(self):
            calls.append(("kill",))

    server = {"proc": _Proc(), "base": "http://127.0.0.1:1", "admin": "adm"}
    monkeypatch.setattr(cb, "_SERVER", server)
    monkeypatch.setattr(
        cb.httpx, "post", lambda url, **kw: calls.append(("post", url, kw["headers"]))
    )
    cb._stop_server()
    assert calls == [("post", "http://127.0.0.1:1/stop", {"x-admin-key": "adm"}), ("kill",)]


def test_typing_into_a_page_is_egress_but_reading_is_not():
    guard = EgressGuard.__new__(EgressGuard)
    assert guard._detect_egress("camofox_browser", {"action": "type", "text": "x"})[1]
    assert not guard._detect_egress("camofox_browser", {"action": "snapshot"})[1]


async def test_a_missing_install_says_how_to_install(monkeypatch, tmp_path):
    monkeypatch.setattr(cb, "_server_script", lambda config: None)
    monkeypatch.setattr(cb, "_SERVER", None)

    async def _public(host):
        return True

    monkeypatch.setattr(cb, "_is_public_host", _public)
    result = await CamofoxBrowserTool().execute(action="open", url="https://example.com")
    assert result.is_error and "CAMOFOX_PATH" in result.error


def test_the_registry_offers_it_to_research_roles():
    from weebot.tools.tool_registry import RoleBasedToolRegistry

    for role in ("researcher", "admin", "webhook"):
        assert "camofox_browser" in RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS[role]
    assert RoleBasedToolRegistry.build_tool_class_map().get("camofox_browser") is CamofoxBrowserTool


def test_the_builtin_skill_says_when_to_use_it():
    from weebot.application.skills.skill_registry import SkillRegistry

    registry = SkillRegistry()
    registry.load_all()
    skill = registry.get("camofox-browser")
    assert skill is not None
    assert "camofox_browser" in skill.content and "CAPTCHA" in skill.content
