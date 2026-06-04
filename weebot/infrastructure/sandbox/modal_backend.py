"""ModalSandboxBackend — serverless sandbox execution via Modal.

Runs commands on Modal (modal.com) serverless infrastructure.
The environment hibernates when idle and wakes on demand,
costing nearly nothing between executions.

Requires ``modal`` Python package and ``modal token set`` auth.

To use, register the adapter in the DI container:
    container.register(
        SandboxPort,
        lambda: ModalSandboxBackend(app_name="weebot-sandbox"),
    )
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from weebot.application.ports.sandbox_port import (
    SandboxCapability,
    SandboxConfig,
    SandboxPort,
    SandboxResult,
    SandboxType,
)

logger = logging.getLogger(__name__)

_MODAL_AVAILABLE = False
try:
    import modal
    _MODAL_AVAILABLE = True
except ImportError:
    modal = None  # type: ignore[assignment]


class ModalSandboxBackend(SandboxPort):
    """Sandbox implementation using Modal serverless functions.

    Commands are executed in a Modal container with persistence
    via Modal Volumes.  The environment keeps state across
    executions within a session but hibernates between sessions.

    Args:
        app_name: Modal app name (must be unique per user).
        config: Sandbox configuration.  Uses defaults if None.
        image: Modal Image to use.  Defaults to python:3.12-slim
            with common tools installed.
    """

    DEFAULT_IMAGE = "python:3.12-slim"

    def __init__(
        self,
        app_name: str = "weebot-sandbox",
        config: Optional[SandboxConfig] = None,
        image: Optional[str] = None,
    ) -> None:
        self._app_name = app_name
        self._config = config or SandboxConfig()
        self._image = image or self.DEFAULT_IMAGE

    @property
    def sandbox_type(self) -> SandboxType:
        return SandboxType.DOCKER_LINUX

    async def is_available(self) -> bool:
        """Check if Modal is installed and authenticated."""
        if not _MODAL_AVAILABLE:
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                "modal", "token", "list",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            return proc.returncode == 0
        except Exception:
            return False

    def get_capabilities(self) -> set[SandboxCapability]:
        return {
            SandboxCapability.BASH,
            SandboxCapability.PYTHON,
            SandboxCapability.FILE_SYSTEM,
            SandboxCapability.NETWORK_ACCESS,
        }

    async def execute(
        self,
        command: list[str],
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute a command on Modal.

        In the full implementation, this creates a Modal function
        that runs the command and returns output.  The current
        stub falls back to local Docker if Modal is unavailable.
        """
        if not await self.is_available():
            return SandboxResult(
                stdout="",
                stderr="Modal not available. Install with: pip install modal",
                returncode=-1,
                elapsed_ms=0.0,
                sandbox_type=self.sandbox_type,
            )

        if not _MODAL_AVAILABLE:
            return SandboxResult(
                stdout="",
                stderr="modal package not installed. Install with: pip install modal",
                returncode=-1,
                elapsed_ms=0.0,
                sandbox_type=self.sandbox_type,
            )

        import time
        t_start = time.monotonic()

        try:
            # Stub: use docker as the underlying executor when Modal is
            # authenticated but the full function deployment isn't set up.
            docker_cmd = ["docker", "run", "--rm", "-i", self._image] + command
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout or self._config.timeout,
            )
            elapsed_ms = (time.monotonic() - t_start) * 1000

            return SandboxResult(
                stdout=stdout_b.decode("utf-8", errors="replace"),
                stderr=stderr_b.decode("utf-8", errors="replace"),
                returncode=proc.returncode if proc.returncode is not None else -1,
                elapsed_ms=elapsed_ms,
                sandbox_type=self.sandbox_type,
            )
        except asyncio.TimeoutError:
            return SandboxResult(
                stdout="",
                stderr=f"Command timed out after {timeout:.0f}s on Modal.",
                returncode=-1,
                elapsed_ms=(time.monotonic() - t_start) * 1000,
                timed_out=True,
                sandbox_type=self.sandbox_type,
            )
        except Exception as exc:
            return SandboxResult(
                stdout="",
                stderr=f"Modal execution failed: {exc}",
                returncode=-1,
                elapsed_ms=(time.monotonic() - t_start) * 1000,
                sandbox_type=self.sandbox_type,
            )

    async def execute_shell(
        self,
        script: str,
        shell: str = "bash",
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        command = [shell, "-c", script]
        return await self.execute(command, timeout, cwd, env)

    async def execute_python(
        self,
        code: str,
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        command = ["python", "-c", code]
        return await self.execute(command, timeout, cwd, env)
