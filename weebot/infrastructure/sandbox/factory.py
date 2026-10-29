"""SandboxFactory — factory for creating sandbox instances.

Provides auto-detection and selection of the best available sandbox
for the current environment.
"""

from __future__ import annotations

import logging

from weebot.application.ports.sandbox_port import (
    SandboxCapability,
    SandboxConfig,
    SandboxPort,
    SandboxResult,
    SandboxType,
)

# Mode string → SandboxType mapping for the WEEBOT_SANDBOX_MODE toggle
MODE_TO_TYPE: dict[str, SandboxType] = {
    "native": SandboxType.NATIVE_WINDOWS,
    "docker": SandboxType.DOCKER_LINUX,
    "wsl2": SandboxType.WSL2,
    "modal": SandboxType.MODAL,
}
from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox
from weebot.infrastructure.sandbox.wsl2 import WSL2Sandbox

try:
    from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox

    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

logger = logging.getLogger(__name__)


class SandboxFactory:
    """Factory for creating and selecting sandbox implementations.

    The factory can auto-detect the best available sandbox or create
    specific implementations as requested.

    Priority order for auto-selection:
    1. Docker (most isolated)
    2. WSL2 (Linux environment on Windows)
    3. Native Windows (fallback)

    Example:
        factory = SandboxFactory()

        # Auto-select best sandbox
        sandbox = factory.create_default()

        # Create specific sandbox
        docker = factory.create(SandboxType.DOCKER_LINUX)

        # Create with custom config
        config = SandboxConfig(timeout=60.0, memory_limit_mb=512)
        sandbox = factory.create_default(config)
    """

    # Priority order for auto-selection (most isolated first)
    DEFAULT_PRIORITY = [SandboxType.DOCKER_LINUX, SandboxType.WSL2, SandboxType.NATIVE_WINDOWS]

    def __init__(self):
        """Initialize the sandbox factory."""
        self._sandbox_classes: dict[SandboxType, type[SandboxPort]] = {
            SandboxType.NATIVE_WINDOWS: NativeWindowsSandbox,
            SandboxType.WSL2: WSL2Sandbox,
        }

        if DOCKER_AVAILABLE:
            self._sandbox_classes[SandboxType.DOCKER_LINUX] = DockerLinuxSandbox
        # Remote and billed: only an explicit SANDBOX_MODE=modal picks it.
        from weebot.infrastructure.sandbox.modal_backend import ModalSandboxBackend

        self._sandbox_classes[SandboxType.MODAL] = ModalSandboxBackend

    async def detect_available(
        self, required_capabilities: set[SandboxCapability] | None = None
    ) -> list[SandboxType]:
        """Detect available sandbox types on this system.

        Args:
            required_capabilities: If specified, only return sandboxes
                that support all these capabilities.

        Returns:
            List of available sandbox types, ordered by priority.
        """
        available: list[SandboxType] = []

        for sandbox_type in self.DEFAULT_PRIORITY:
            if sandbox_type not in self._sandbox_classes:
                continue

            try:
                sandbox_class = self._sandbox_classes[sandbox_type]
                instance = sandbox_class()

                if await instance.is_available():
                    if required_capabilities is None or required_capabilities.issubset(
                        instance.get_capabilities()
                    ):
                        available.append(sandbox_type)
            except Exception as e:
                logger.debug(f"Error checking {sandbox_type.name}: {e}")

        return available

    def create(self, sandbox_type: SandboxType, config: SandboxConfig | None = None) -> SandboxPort:
        """Create a specific sandbox implementation.

        Args:
            sandbox_type: The type of sandbox to create.
            config: Optional configuration for the sandbox.

        Returns:
            Configured sandbox instance.

        Raises:
            ValueError: If the sandbox type is unknown or not available.
        """
        if sandbox_type not in self._sandbox_classes:
            raise ValueError(f"Unknown sandbox type: {sandbox_type.name}")

        sandbox_class = self._sandbox_classes[sandbox_type]
        return sandbox_class(config)

    async def create_default(
        self,
        config: SandboxConfig | None = None,
        required_capabilities: set[SandboxCapability] | None = None,
        mode: str = "auto",
    ) -> SandboxPort:
        """Create the best available sandbox.

        Selects the highest-priority sandbox that is available on this
        system and supports the required capabilities.

        When *mode* is not ``"auto"``, attempts to create the specific
        sandbox type directly (``native``, ``docker``, ``wsl2``) and
        raises ``RuntimeError`` if that type is not available.

        Args:
            config: Optional configuration for the sandbox.
            required_capabilities: Required capabilities for the sandbox.
            mode: Sandbox selection mode — ``"auto"`` (default, detect
                best available), or a specific type from
                ``{"native", "docker", "wsl2"}``.

        Returns:
            Configured sandbox instance.

        Raises:
            RuntimeError: If no suitable sandbox is available, or if
                the requested *mode* is not available on this system.
            ValueError: If *mode* is not a recognized value.
        """
        if mode != "auto":
            sandbox_type = MODE_TO_TYPE.get(mode.lower())
            if sandbox_type is None:
                raise ValueError(
                    f"Unknown sandbox mode: '{mode}'. " f"Use one of: auto, native, docker, wsl2."
                )
            if sandbox_type not in self._sandbox_classes:
                raise RuntimeError(
                    f"Sandbox mode '{mode}' ({sandbox_type.name}) is not "
                    f"available on this system (dependency not installed)."
                )
            # Quick availability check
            instance = self._sandbox_classes[sandbox_type]()
            if not await instance.is_available():
                raise RuntimeError(
                    f"Sandbox mode '{mode}' ({sandbox_type.name}) is not "
                    f"available on this system (runtime check failed)."
                )
            logger.info("Selected sandbox via mode toggle: %s (%s)", sandbox_type.name, mode)
            return self.create(sandbox_type, config)

        available = await self.detect_available(required_capabilities)

        if not available:
            if required_capabilities:
                raise RuntimeError(
                    f"No sandbox available with capabilities: {required_capabilities}"
                )
            else:
                raise RuntimeError("No sandbox available on this system")

        selected = available[0]
        logger.info("Auto-selected sandbox: %s", selected.name)

        return self.create(selected, config)

    async def create_fallback_chain(
        self, config: SandboxConfig | None = None
    ) -> FallbackSandboxChain:
        """Create a fallback chain of sandboxes.

        The fallback chain tries each sandbox in order until one succeeds.

        Args:
            config: Optional configuration for sandboxes.

        Returns:
            FallbackSandboxChain instance.
        """
        available = await self.detect_available()
        sandboxes = [self.create(st, config) for st in available]
        return FallbackSandboxChain(sandboxes)


class FallbackSandboxChain:
    """Chain of sandboxes that falls back on failure.

    Attempts to execute with each sandbox in order until one succeeds.
    Useful for resilient execution across different environments.

    Example:
        chain = await factory.create_fallback_chain()
        result = await chain.execute(["python", "-c", "print('hello')"])
    """

    def __init__(self, sandboxes: list[SandboxPort]):
        """Initialize with a list of sandboxes to try.

        Args:
            sandboxes: Ordered list of sandboxes to attempt.
        """
        self._sandboxes = sandboxes

    async def execute(
        self,
        command: list[str],
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        """Execute command with fallback.

        Tries each sandbox in order until one succeeds (returncode == 0)
        or all have been attempted.

        Args:
            command: Command to execute.
            timeout: Timeout in seconds.
            cwd: Working directory.
            env: Environment variables.
            memory_limit_mb: Optional memory limit in MB.

        Returns:
            SandboxResult from the first successful sandbox, or the last
            attempted sandbox if all failed.
        """
        last_result: SandboxResult | None = None

        for sandbox in self._sandboxes:
            try:
                result = await sandbox.execute(command, timeout, cwd, env, memory_limit_mb)
                last_result = result

                if result.success:
                    return result

                logger.debug(
                    f"Sandbox {sandbox.sandbox_type.name} failed with rc={result.returncode}"
                )
            except Exception as e:
                logger.warning(f"Sandbox {sandbox.sandbox_type.name} error: {e}")

        # Return last result or error if none attempted
        if last_result is not None:
            return last_result

        return SandboxResult(
            stdout="",
            stderr="No sandboxes available in fallback chain",
            returncode=-1,
            elapsed_ms=0.0,
            sandbox_type=SandboxType.NATIVE_WINDOWS,
        )

    async def execute_shell(
        self,
        script: str,
        shell: str = "bash",
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        """Execute shell script with fallback."""
        last_result: SandboxResult | None = None

        for sandbox in self._sandboxes:
            try:
                result = await sandbox.execute_shell(
                    script, shell, timeout, cwd, env, memory_limit_mb
                )
                last_result = result

                if result.success:
                    return result
            except Exception as e:
                logger.warning(f"Sandbox {sandbox.sandbox_type.name} error: {e}")

        if last_result is not None:
            return last_result

        return SandboxResult(
            stdout="",
            stderr="No sandboxes available in fallback chain",
            returncode=-1,
            elapsed_ms=0.0,
            sandbox_type=SandboxType.NATIVE_WINDOWS,
        )

    async def execute_python(
        self,
        code: str,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        """Execute Python code with fallback."""
        last_result: SandboxResult | None = None

        for sandbox in self._sandboxes:
            try:
                result = await sandbox.execute_python(code, timeout, cwd, env, memory_limit_mb)
                last_result = result

                if result.success:
                    return result
            except Exception as e:
                logger.warning(f"Sandbox {sandbox.sandbox_type.name} error: {e}")

        if last_result is not None:
            return last_result

        return SandboxResult(
            stdout="",
            stderr="No sandboxes available in fallback chain",
            returncode=-1,
            elapsed_ms=0.0,
            sandbox_type=SandboxType.NATIVE_WINDOWS,
        )


# Convenience functions for quick access


async def get_default_sandbox(config: SandboxConfig | None = None) -> SandboxPort:
    """Get the best available sandbox.

    Args:
        config: Optional configuration.

    Returns:
        Best available sandbox instance.
    """
    factory = SandboxFactory()
    return await factory.create_default(config)


def get_sandbox(sandbox_type: SandboxType, config: SandboxConfig | None = None) -> SandboxPort:
    """Get a specific sandbox type.

    Args:
        sandbox_type: Type of sandbox to create.
        config: Optional configuration.

    Returns:
        Configured sandbox instance.
    """
    factory = SandboxFactory()
    return factory.create(sandbox_type, config)


def create_default_sandbox() -> SandboxPort:
    """Create the default sandbox for the current environment (synchronous).

    Honors ``WeebotSettings.sandbox_mode`` (auto | native | docker | wsl2).
    In ``auto`` mode, selects NativeWindowsSandbox on Windows and
    DockerLinuxSandbox elsewhere.  This is the single source of truth for the
    "no sandbox injected" default, shared by the DI container and the
    bash/python tools so their behaviour can never drift apart.
    """
    import sys

    from weebot.config.settings import get_settings

    settings = get_settings()
    config = build_sandbox_config(settings)
    mode = (settings.sandbox_mode or "auto").lower()
    platform_default = NativeWindowsSandbox if sys.platform == "win32" else DockerLinuxSandbox
    if mode == "auto":
        sandbox = platform_default(config)
    elif mode == "docker_first":
        # ADR-014, opt-in: the isolating backend when it can actually run.
        if DOCKER_AVAILABLE and _docker_ready():
            sandbox = DockerLinuxSandbox(config)
        else:
            logger.warning(
                "SANDBOX_MODE=docker_first: Docker is not running or %s is not built; "
                "using %s. Build the image with: %s",
                DockerLinuxSandbox.CUSTOM_IMAGE,
                platform_default.__name__,
                DockerLinuxSandbox.BUILD_HINT,
            )
            sandbox = platform_default(config)
    else:
        sandbox_type = MODE_TO_TYPE.get(mode)
        if sandbox_type is None:
            raise ValueError(
                f"Unknown sandbox_mode '{settings.sandbox_mode}'. "
                f"Set SANDBOX_MODE to: auto, docker_first, native, docker, wsl2, modal."
            )
        sandbox = SandboxFactory().create(sandbox_type, config)
    if (
        settings.sandbox_require_isolation
        and not config.allow_network
        and not sandbox.has_capability(SandboxCapability.NETWORK_ISOLATION)
    ):
        return IsolationRequiredSandbox(sandbox)
    _warn_if_network_off_is_best_effort(sandbox, config)
    return sandbox


def _docker_ready() -> bool:
    """Docker answers and weebot-tool-env is built (one sync check at startup)."""
    from weebot.infrastructure.sandbox._docker_probe import docker_ready

    return docker_ready(DockerLinuxSandbox.CUSTOM_IMAGE)


class IsolationRequiredSandbox(SandboxPort):
    """Refuses every call: the backend cannot enforce network-off (ADR-014 strict)."""

    def __init__(self, inner: SandboxPort) -> None:
        self._inner = inner

    @property
    def sandbox_type(self) -> SandboxType:
        return self._inner.sandbox_type

    async def is_available(self) -> bool:
        return await self._inner.is_available()

    def get_capabilities(self) -> set[SandboxCapability]:
        return self._inner.get_capabilities()

    def _refusal(self) -> SandboxResult:
        return SandboxResult(
            stdout="",
            stderr=(
                f"SANDBOX_REQUIRE_ISOLATION=true and {type(self._inner).__name__} cannot "
                "isolate the network. Use SANDBOX_MODE=docker (or docker_first with "
                f"{DockerLinuxSandbox.CUSTOM_IMAGE} built), or turn strict mode off."
            ),
            returncode=-1,
            elapsed_ms=0.0,
            sandbox_type=self._inner.sandbox_type,
        )

    async def execute(self, command, timeout=None, cwd=None, env=None, memory_limit_mb=None):
        return self._refusal()

    async def execute_shell(
        self, script, shell="bash", timeout=None, cwd=None, env=None, memory_limit_mb=None
    ):
        return self._refusal()

    async def execute_python(
        self, code, timeout=None, cwd=None, env=None, memory_limit_mb=None
    ):
        return self._refusal()


def build_sandbox_config(settings) -> SandboxConfig:
    """The one SandboxConfig the default sandbox runs with (W3.9, F29).

    ``sandbox_allow_network`` and ``sandbox_max_output_bytes`` had no reader
    before this: every sandbox ran with ``SandboxConfig()`` defaults, network
    on. Network is now off unless the setting says otherwise; a single call
    gets network only when ToolExecutor clears its egress (ADR-013).
    """
    return SandboxConfig(
        max_output_bytes=settings.sandbox_max_output_bytes,
        allow_network=settings.sandbox_allow_network,
        # Docker mounts it read-only at /workspace, Output/ writable (ADR-014).
        # The native backends run in the host folder and ignore it.
        workspace_dir=_workspace_root(),
    )


def _workspace_root():
    from weebot.config.settings import WORKSPACE_ROOT

    return WORKSPACE_ROOT


_warned_network: set[str] = set()


def _warn_if_network_off_is_best_effort(sandbox: SandboxPort, config: SandboxConfig) -> None:
    if config.allow_network or sandbox.has_capability(SandboxCapability.NETWORK_ISOLATION):
        return
    name = type(sandbox).__name__
    if name not in _warned_network:
        _warned_network.add(name)
        logger.warning(
            "%s cannot isolate the network: 'network off' is best effort (dead proxy "
            "variables on native Windows, nothing on WSL2); raw sockets still connect. "
            "Use SANDBOX_MODE=docker for real isolation.",
            name,
        )
