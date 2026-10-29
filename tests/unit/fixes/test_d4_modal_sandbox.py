"""D4: SANDBOX_MODE=modal runs commands in a Modal sandbox.

ModalSandboxBackend was a stub: it checked for the `modal` CLI and then ran a
LOCAL `docker run` without any of DockerLinuxSandbox's hardening, ignored cwd,
env and output limits, and nothing could select it. It now creates a
`modal.Sandbox` (network blocked unless the call is cleared for it), runs the
command there and terminates it. The `modal` package is optional and not
installed here, so these tests drive a fake module; the real SDK is unverified.
"""

import asyncio
from types import SimpleNamespace

import pytest

from weebot.application.ports.sandbox_port import (
    SandboxCapability,
    SandboxConfig,
    SandboxType,
    network_cleared_for_call,
)
from weebot.infrastructure.sandbox import modal_backend as mb


class _Aio:
    """A Modal-style callable: sync call, plus `.aio` for the async form."""

    def __init__(self, fn):
        self._fn = fn

    def __call__(self, *a, **k):
        return self._fn(*a, **k)

    async def aio(self, *a, **k):
        result = self._fn(*a, **k)
        if asyncio.iscoroutine(result):
            return await result
        return result


def _fake_modal(stdout=b"ok", stderr=b"", returncode=0, hang=False):
    seen = {"terminated": False}

    class _Stream:
        def __init__(self, data):
            self.read = _Aio(lambda: data.decode())

    class _Process:
        def __init__(self):
            self.stdout = _Stream(stdout)
            self.stderr = _Stream(stderr)

            async def wait():
                if hang:
                    await asyncio.sleep(10)
                return returncode

            self.wait = _Aio(wait)

    class _Sandbox:
        def __init__(self):
            def exec_(*command, **kwargs):
                seen["command"], seen["exec_kwargs"] = command, kwargs
                return _Process()

            def terminate():
                seen["terminated"] = True

            self.exec = _Aio(exec_)
            self.terminate = _Aio(terminate)

    def create(**kwargs):
        seen["create_kwargs"] = kwargs
        return _Sandbox()

    module = SimpleNamespace(
        App=SimpleNamespace(lookup=_Aio(lambda name, create_if_missing: f"app:{name}")),
        Image=SimpleNamespace(from_registry=lambda ref: f"image:{ref}"),
        Secret=SimpleNamespace(from_dict=lambda d: ("secret", dict(d))),
        Sandbox=SimpleNamespace(create=_Aio(create)),
    )
    return module, seen


@pytest.fixture
def modal(monkeypatch):
    def install(**kwargs):
        module, seen = _fake_modal(**kwargs)
        monkeypatch.setattr(mb, "modal", module)
        monkeypatch.setattr(mb, "_MODAL_AVAILABLE", True)
        return seen

    return install


async def test_a_command_runs_in_a_modal_sandbox_with_the_network_blocked(modal):
    seen = modal(stdout=b"hello")
    backend = mb.ModalSandboxBackend(SandboxConfig())
    result = await backend.execute(["echo", "hello"], cwd="/work", env={"A": "1"})
    assert result.success and result.stdout == "hello"
    assert seen["command"] == ("echo", "hello")
    assert seen["create_kwargs"]["block_network"] is True
    assert seen["exec_kwargs"]["workdir"] == "/work"
    assert ("secret", {"A": "1"}) in seen["create_kwargs"]["secrets"]
    assert seen["terminated"] is True


async def test_a_call_cleared_for_the_network_gets_it(modal):
    seen = modal()
    with network_cleared_for_call():
        await mb.ModalSandboxBackend(SandboxConfig()).execute(["curl", "x"])
    assert seen["create_kwargs"]["block_network"] is False


async def test_output_is_capped_and_a_timeout_is_reported(modal):
    modal(stdout=b"x" * 500)
    result = await mb.ModalSandboxBackend(SandboxConfig(max_output_bytes=100)).execute(["cat"])
    assert len(result.stdout) <= 100 + 80  # the cap plus its truncation note

    seen = modal(hang=True)
    result = await mb.ModalSandboxBackend(SandboxConfig()).execute(["sleep"], timeout=0.05)
    assert result.timed_out and seen["terminated"] is True


def test_capabilities_say_whether_the_network_is_isolated():
    assert SandboxCapability.NETWORK_ISOLATION in mb.ModalSandboxBackend(
        SandboxConfig()
    ).get_capabilities()
    assert SandboxCapability.NETWORK_ISOLATION not in mb.ModalSandboxBackend(
        SandboxConfig(allow_network=True)
    ).get_capabilities()
    assert mb.ModalSandboxBackend().sandbox_type is SandboxType.MODAL


def test_sandbox_mode_modal_selects_it():
    from weebot.config.settings import WeebotSettings
    from weebot.infrastructure.sandbox.factory import MODE_TO_TYPE, SandboxFactory

    assert WeebotSettings.validate_sandbox_mode("modal") == "modal"
    assert MODE_TO_TYPE["modal"] is SandboxType.MODAL
    sandbox = SandboxFactory().create(SandboxType.MODAL, SandboxConfig(timeout=7))
    assert isinstance(sandbox, mb.ModalSandboxBackend) and sandbox._config.timeout == 7
