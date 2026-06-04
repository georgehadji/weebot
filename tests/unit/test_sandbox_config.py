"""Unit tests for sandbox mode configuration (Enhancement 1).

Covers:
- WeebotSettings.sandbox_mode validation
- SandboxFactory.create_default() mode redirection
- DI container sandbox creation respects the setting
"""
import pytest
from pydantic import ValidationError


class TestSandboxModeSetting:
    """Validates the sandbox_mode field in WeebotSettings."""

    def test_default_is_auto(self, with_openai_key):
        from weebot.config.settings import WeebotSettings

        settings = WeebotSettings()
        assert settings.sandbox_mode == "auto"

    def test_accepts_auto(self, with_openai_key, monkeypatch):
        """'auto' is the default and is accepted."""
        from weebot.config.settings import WeebotSettings

        monkeypatch.setenv("SANDBOX_MODE", "auto")
        settings = WeebotSettings()
        assert settings.sandbox_mode == "auto"

    def test_accepts_native(self, with_openai_key, monkeypatch):
        from weebot.config.settings import WeebotSettings

        monkeypatch.setenv("SANDBOX_MODE", "native")
        settings = WeebotSettings()
        assert settings.sandbox_mode == "native"

    def test_accepts_docker(self, with_openai_key, monkeypatch):
        from weebot.config.settings import WeebotSettings

        monkeypatch.setenv("SANDBOX_MODE", "docker")
        settings = WeebotSettings()
        assert settings.sandbox_mode == "docker"

    def test_accepts_wsl2(self, with_openai_key, monkeypatch):
        from weebot.config.settings import WeebotSettings

        monkeypatch.setenv("SANDBOX_MODE", "wsl2")
        settings = WeebotSettings()
        assert settings.sandbox_mode == "wsl2"

    def test_is_case_insensitive(self, with_openai_key, monkeypatch):
        from weebot.config.settings import WeebotSettings

        monkeypatch.setenv("SANDBOX_MODE", "DOCKER")
        settings = WeebotSettings()
        assert settings.sandbox_mode == "docker"

    def test_rejects_invalid_mode(self, with_openai_key, monkeypatch):
        from weebot.config.settings import WeebotSettings

        monkeypatch.setenv("SANDBOX_MODE", "lxc")
        with pytest.raises(ValidationError, match="sandbox_mode must be one of"):
            WeebotSettings()

    def test_rejects_empty_string(self, with_openai_key, monkeypatch):
        from weebot.config.settings import WeebotSettings

        monkeypatch.setenv("SANDBOX_MODE", "")
        with pytest.raises(ValidationError, match="sandbox_mode must be one of"):
            WeebotSettings()


class TestSandboxFactoryMode:
    """Validates SandboxFactory.create_default() mode parameter."""

    @pytest.fixture(autouse=True)
    def _reset_factory(self):
        """Ensure fresh factory for each test."""
        yield

    @pytest.mark.asyncio
    async def test_auto_mode_delegates_to_detection(self, mocker):
        """With mode='auto', detect_available is called for auto-selection."""
        from weebot.infrastructure.sandbox.factory import SandboxFactory
        from weebot.application.ports.sandbox_port import SandboxType

        factory = SandboxFactory()
        # Mock detect_available to return a known value
        mocker.patch.object(factory, "detect_available", return_value=[SandboxType.WSL2])
        spy_create = mocker.spy(factory, "create")

        result = await factory.create_default(mode="auto")

        factory.detect_available.assert_awaited_once()
        spy_create.assert_called_once_with(SandboxType.WSL2, None)
        assert result is not None

    @pytest.mark.asyncio
    async def test_native_mode_creates_native_windows(self, mocker):
        """With mode='native', create NativeWindowsSandbox."""
        from weebot.infrastructure.sandbox.factory import SandboxFactory
        from weebot.application.ports.sandbox_port import SandboxType
        from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox

        factory = SandboxFactory()
        # Mock is_available to pass
        mocker.patch.object(NativeWindowsSandbox, "is_available", return_value=True)

        result = await factory.create_default(mode="native")

        assert isinstance(result, NativeWindowsSandbox)

    @pytest.mark.asyncio
    async def test_rejects_unknown_mode(self):
        """With mode='lxc', raises ValueError."""
        from weebot.infrastructure.sandbox.factory import SandboxFactory

        factory = SandboxFactory()
        with pytest.raises(ValueError, match="Unknown sandbox mode"):
            await factory.create_default(mode="lxc")

    @pytest.mark.skipif("not hasattr(pytest, 'docker_test')")
    @pytest.mark.asyncio
    async def test_docker_mode_creates_docker(self, mocker):
        """With mode='docker', create DockerLinuxSandbox when available."""
        from weebot.infrastructure.sandbox.factory import SandboxFactory
        from weebot.application.ports.sandbox_port import SandboxType

        factory = SandboxFactory()
        # This test is architecture-dependent; skip if Docker isn't built
        if SandboxType.DOCKER_LINUX not in factory._sandbox_classes:
            pytest.skip("DockerLinuxSandbox not available in this build")

        from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox
        from weebot.infrastructure.sandbox.factory import DOCKER_AVAILABLE

        if not DOCKER_AVAILABLE:
            pytest.skip("Docker not available")

        mocker.patch.object(DockerLinuxSandbox, "is_available", return_value=True)
        result = await factory.create_default(mode="docker")
        assert isinstance(result, DockerLinuxSandbox)


class TestSandboxModeInDI:
    """Validates that the DI container respects WEEBOT_SANDBOX_MODE."""

    def test_di_creates_with_mode_auto(self, with_openai_key):
        """Default auto mode creates platform-appropriate sandbox."""
        from weebot.application.di import Container
        from weebot.application.ports.sandbox_port import SandboxPort

        container = Container()
        container.configure_defaults()

        sandbox = container.get(SandboxPort)
        # Should not raise; type depends on platform
        assert sandbox is not None

    def test_di_creates_native_when_mode_is_native(self, with_openai_key, monkeypatch):
        """When SANDBOX_MODE=native, DI creates NativeWindowsSandbox."""
        monkeypatch.setenv("SANDBOX_MODE", "native")
        from weebot.application.di import Container
        from weebot.application.ports.sandbox_port import SandboxPort
        from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox

        container = Container()
        container.configure_defaults()

        sandbox = container.get(SandboxPort)
        assert isinstance(sandbox, NativeWindowsSandbox)

    def test_di_rejects_unknown_mode(self, with_openai_key, monkeypatch):
        """When SANDBOX_MODE is invalid, DI raises on resolution."""
        monkeypatch.setenv("SANDBOX_MODE", "lxc")
        from weebot.application.di import Container
        from weebot.application.ports.sandbox_port import SandboxPort

        container = Container()
        container.configure_defaults()

        with pytest.raises((ValueError, KeyError)):
            container.get(SandboxPort)
