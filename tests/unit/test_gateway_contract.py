"""H28: every gateway adapter keeps the same contract, and the registry finds them."""

from __future__ import annotations

import ast
import dataclasses
import types
from importlib import metadata
from pathlib import Path

import pytest

from weebot.domain.models import gateway_command
from weebot.domain.models.gateway_command import (
    Compress,
    ListTools,
    McpStatus,
    NewSession,
    Reply,
    ResumeSession,
    SetModel,
    StopRun,
)
from weebot.domain.models.gateway_session import GatewaySessionKey
from weebot.interfaces.gateways import base, registry
from weebot.interfaces.gateways.base import ChannelCapabilities, GatewayAdapter
from weebot.interfaces.gateways.registry import GatewayRegistry

GATEWAY_DIR = Path(base.__file__).parent
KEY = GatewaySessionKey(platform="web", chat_type="private", chat_id="1")


class _Port:
    pass


async def _async_none(*_args, **_kwargs):
    return None


def _adapter(cls: type[GatewayAdapter]) -> GatewayAdapter:
    """A real instance with stub collaborators; nothing connects until start()."""
    state, llm = _Port(), _Port()
    name = cls.name
    if name == "telegram":
        resolver = types.SimpleNamespace(close=_async_none)
        return cls(token="t", state_repo=state, llm=llm, flow_resolver=resolver)
    if name == "discord":
        return cls("00" * 32, "bot", "app", state, llm)
    if name == "slack":
        return cls("secret", "bot", state, llm)
    if name == "whatsapp":
        return cls("tok", "123", state, llm)
    if name == "signal":
        return cls(state, llm, account_number="+10000000000")
    if name == "email":
        return cls(state, llm, imap_user="a@example.org", imap_password="p")
    raise AssertionError(f"no test factory for {name}")


@pytest.fixture(params=GatewayRegistry().names())
def adapter_class(request) -> type[GatewayAdapter]:
    cls = GatewayRegistry().get(request.param)
    assert cls is not None
    return cls


class _Bare(GatewayAdapter):
    name = "bare"
    capabilities = ChannelCapabilities(max_len=10)

    async def start(self): ...
    async def stop(self): ...
    async def send_response(self, response): ...


class DemoAdapter(_Bare):
    name = "demo"


def test_every_built_in_names_itself_and_declares_what_it_can_do(adapter_class):
    assert adapter_class.name and adapter_class.name == adapter_class.name.lower()
    assert isinstance(adapter_class.capabilities, ChannelCapabilities)
    assert registry._BUILT_IN[adapter_class.name].endswith(adapter_class.__name__)


def test_a_chat_not_on_the_allowlist_is_refused(adapter_class, monkeypatch):
    settings = types.SimpleNamespace(gateway_auth_enabled=True)
    monkeypatch.setattr("weebot.config.settings.get_settings", lambda: settings)
    adapter = _adapter(adapter_class)
    monkeypatch.setattr(adapter._auth, "is_platform_allowed", lambda platform: False)

    assert adapter.is_authorized(adapter_class.name, "1", "u") is False


RESULTS = [
    Reply("hi"),
    NewSession(),
    StopRun(),
    SetModel("m"),
    ResumeSession(),
    ListTools(),
    McpStatus(),
    Compress(),
]


def test_the_list_above_covers_every_command_result():
    assert {type(r) for r in RESULTS} == set(gateway_command.CommandResult.__args__)


@pytest.mark.parametrize("result", RESULTS, ids=lambda r: type(r).__name__)
async def test_every_command_result_gets_a_text_reply(adapter_class, result):
    adapter = _adapter(adapter_class)

    reply = await adapter.apply_command(result, KEY)

    assert isinstance(reply, str) and reply


async def test_a_command_an_adapter_cannot_do_says_so_by_name():
    reply = await _Bare(llm_port=_Port()).apply_command(Compress(), KEY)

    assert reply == "/compress is not available on bare yet."


def test_a_long_reply_is_cut_to_the_channel_limit_without_losing_text(adapter_class):
    limit = adapter_class.capabilities.max_len
    if not limit:
        pytest.skip("no limit")
    adapter = _adapter(adapter_class)
    text = "\n\n".join(f"paragraph {i} " + "word " * 40 for i in range(80))

    pieces = adapter.split_text(text)

    assert len(pieces) > 1 and all(0 < len(p) <= limit for p in pieces)
    assert " ".join(" ".join(pieces).split()) == " ".join(text.split())


def test_text_with_no_break_is_still_cut():
    assert _Bare(llm_port=_Port()).split_text("x" * 25) == ["x" * 10, "x" * 10, "x" * 5]


def test_no_adapter_imports_another():
    adapters = {p.stem for p in GATEWAY_DIR.glob("*.py")} & set(registry._BUILT_IN)
    for stem in adapters:
        tree = ast.parse((GATEWAY_DIR / f"{stem}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for imported in names:
                other = imported.rpartition(".")[2]
                clash = imported.startswith("weebot.interfaces.gateways.") and other in (
                    adapters - {stem}
                )
                assert not clash, f"{stem} imports {imported}"


def test_the_polling_adapters_build_from_settings():
    settings = types.SimpleNamespace(
        telegram_bot_token="t",
        gateway_session_ttl_seconds=60,
        gateway_max_sessions_per_platform=5,
        signal_account_number="+1",
        signal_cli_rest_url="http://x",
        email_imap_user="u@example.org",
        email_imap_password="p",
        email_imap_server="imap.example.org",
        email_smtp_server="smtp.example.org",
        email_smtp_port=587,
        email_from_address=None,
        email_poll_interval_seconds=30,
        email_trusted_authserv_ids=None,
    )
    container = types.SimpleNamespace(get=lambda port: _Port())
    reg = GatewayRegistry()

    for name in ("telegram", "signal", "email"):
        cls = reg.get(name)
        assert cls.configured(settings) is True
        assert isinstance(cls.build(settings, container), cls)
        assert cls.configured(types.SimpleNamespace()) is False
    for name in ("discord", "slack", "whatsapp"):
        assert reg.get(name).configured(settings) is False  # a router builds these per request


async def test_start_configured_starts_only_what_is_configured_and_survives_a_failure():
    started: list[str] = []

    def make(adapter_name: str, ok: bool, configured: bool):
        class A(GatewayAdapter):
            name = adapter_name

            @classmethod
            def configured(cls, settings):
                return configured

            @classmethod
            def build(cls, settings, container):
                if not ok:
                    raise RuntimeError("boom")
                return cls(llm_port=_Port())

            async def start(self):
                started.append(adapter_name)

            async def stop(self):
                started.remove(adapter_name)

            async def send_response(self, response): ...

        return A

    reg = GatewayRegistry()
    reg._targets = {}
    for n, ok, cfg in (("a", True, True), ("b", False, True), ("c", True, False)):
        reg._classes[n] = make(n, ok, cfg)
        reg._targets[n] = "unused"

    running = await reg.start_configured(object(), object())

    assert set(running) == {"a"} and started == ["a"]
    await registry.stop_all(running)
    assert started == []


def _entry(name: str) -> metadata.EntryPoint:
    return metadata.EntryPoint(
        name=name, value="tests.unit.test_gateway_contract:DemoAdapter", group="weebot.gateways"
    )


def test_an_adapter_from_an_entry_point_is_found(monkeypatch):
    monkeypatch.setattr(metadata, "entry_points", lambda group: [_entry("demo")])
    reg = GatewayRegistry()
    reg.discover()

    assert reg.get("demo") is DemoAdapter and "demo" in reg.names()


def test_an_entry_point_cannot_replace_a_built_in(monkeypatch):
    monkeypatch.setattr(metadata, "entry_points", lambda group: [_entry("telegram")])
    reg = GatewayRegistry()
    reg.discover()

    assert reg.get("telegram").__name__ == "TelegramAdapter"


def test_a_broken_entry_point_is_skipped_not_fatal():
    reg = GatewayRegistry(extra={"bad": "no.such.module:Thing", "notadapter": "pathlib:Path"})

    assert reg.get("bad") is None and reg.get("notadapter") is None
    assert reg.get("telegram") is not None


def test_capabilities_are_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        ChannelCapabilities().max_len = 1  # type: ignore[misc]
