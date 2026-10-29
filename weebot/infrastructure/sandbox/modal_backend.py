"""ModalSandboxBackend — run commands in a Modal (modal.com) sandbox.

Selected with ``SANDBOX_MODE=modal``. Needs the optional ``modal`` package
(``pip install modal``) and a Modal token (``modal token new``, or
``MODAL_TOKEN_ID`` / ``MODAL_TOKEN_SECRET``); every run is billed by Modal.

Each call creates a sandbox from ``image``, runs the command there and
terminates it. The network is blocked unless the config allows it or the call
was cleared for it (``network_cleared_for_call``), which is when
``NETWORK_ISOLATION`` is claimed. Written against Modal's ``Sandbox.create`` /
``exec`` API without the package installed here; tests drive a fake module.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from weebot.application.ports.sandbox_port import (
    SandboxCapability,
    SandboxConfig,
    SandboxPort,
    SandboxResult,
    SandboxType,
    network_allowed,
)

logger = logging.getLogger(__name__)

_MODAL_AVAILABLE = False
try:
    import modal

    _MODAL_AVAILABLE = True
except ImportError:
    modal = None  # type: ignore[assignment]

_TRUNCATION_NOTE = "...[truncated]"


def _token_configured() -> bool:
    from weebot.config.secret_accessor import SecretAccessor

    if SecretAccessor.get("MODAL_TOKEN_ID"):
        return True
    return (Path.home() / ".modal.toml").exists()


class ModalSandboxBackend(SandboxPort):
    """Sandbox on Modal serverless containers.

    Args:
        config: Sandbox configuration; defaults if None. The factory passes it
            positionally, like every other backend.
        app_name: Modal app the sandboxes run under (created when missing).
        image: Registry image to run; python:3.12-slim by default.
    """

    DEFAULT_IMAGE = "python:3.12-slim"

    def __init__(
        self,
        config: SandboxConfig | None = None,
        app_name: str = "weebot-sandbox",
        image: str | None = None,
    ) -> None:
        self._config = config or SandboxConfig()
        self._app_name = app_name
        self._image = image or self.DEFAULT_IMAGE

    @property
    def sandbox_type(self) -> SandboxType:
        return SandboxType.MODAL

    async def is_available(self) -> bool:
        """The package is installed and a token is configured."""
        return _MODAL_AVAILABLE and _token_configured()

    def get_capabilities(self) -> set[SandboxCapability]:
        caps = {SandboxCapability.BASH, SandboxCapability.PYTHON, SandboxCapability.FILE_SYSTEM}
        if self._config.allow_network:
            caps.add(SandboxCapability.NETWORK_ACCESS)
        else:
            caps.add(SandboxCapability.NETWORK_ISOLATION)
        return caps

    def _truncate(self, text: str) -> str:
        limit = self._config.max_output_bytes
        data = text.encode("utf-8", errors="replace")
        if len(data) <= limit:
            return text
        return data[:limit].decode("utf-8", errors="ignore") + _TRUNCATION_NOTE

    async def execute(
        self,
        command: list[str],
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        started = time.monotonic()

        def result(stdout="", stderr="", returncode=-1, timed_out=False) -> SandboxResult:
            return SandboxResult(
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
                elapsed_ms=(time.monotonic() - started) * 1000,
                timed_out=timed_out,
                sandbox_type=self.sandbox_type,
            )

        if not _MODAL_AVAILABLE:
            return result(stderr="Modal not available. Install with: pip install modal")

        limit = timeout or self._config.timeout
        merged_env = {**self._config.env_vars, **(env or {})}
        workdir = str(cwd or self._config.working_dir or "") or None
        sandbox = None
        try:
            app = await modal.App.lookup.aio(self._app_name, create_if_missing=True)
            sandbox = await modal.Sandbox.create.aio(
                app=app,
                image=modal.Image.from_registry(self._image),
                timeout=max(1, int(limit) + 5),
                block_network=not network_allowed(self._config),
                secrets=[modal.Secret.from_dict(merged_env)] if merged_env else [],
                memory=memory_limit_mb or self._config.memory_limit_mb,
            )
            process = await sandbox.exec.aio(*command, workdir=workdir)
            returncode = await asyncio.wait_for(process.wait.aio(), timeout=limit)
            stdout = await process.stdout.read.aio()
            stderr = await process.stderr.read.aio()
            return result(self._truncate(stdout), self._truncate(stderr), returncode)
        except TimeoutError:
            return result(stderr=f"Process killed after {limit:.0f}s timeout.", timed_out=True)
        except Exception as exc:
            logger.warning("Modal sandbox run failed: %s", exc)
            return result(stderr=f"Modal sandbox failed: {exc}")
        finally:
            if sandbox is not None:
                try:
                    await sandbox.terminate.aio()
                except Exception:
                    logger.debug("Modal sandbox terminate failed", exc_info=True)

    async def execute_shell(
        self,
        script: str,
        shell: str = "bash",
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        command = [shell, "-c", script]
        return await self.execute(command, timeout, cwd, env, memory_limit_mb)

    async def execute_python(
        self,
        code: str,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        command = ["python", "-c", code]
        return await self.execute(command, timeout, cwd, env, memory_limit_mb)
