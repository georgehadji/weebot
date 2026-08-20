"""NativeWindowsSandbox — Windows-native process execution with resource limits."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from weebot.application.ports.sandbox_port import (
    SandboxCapability,
    SandboxConfig,
    SandboxPort,
    SandboxResult,
    SandboxType,
)

# ---------------------------------------------------------------------------
# Child environment builder
# ---------------------------------------------------------------------------

# Allowlisted environment variables for child processes.
# Agents running inside the sandbox should NOT inherit API keys or other
# secrets from the parent process.  Legitimate values must be declared
# via SandboxConfig.env_vars.
_ALLOWLISTED_ENV_VARS: set[str] = {
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATHEXT",
    "PYTHONPATH",  # allow python path config
}


def _build_child_env(config: SandboxConfig, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a child process environment from a minimal allowlist.

    Starts from a deny-by-default allowlist (``_ALLOWLISTED_ENV_VARS``),
    adds any ``config.env_vars``, then overlays *extra* on top.  This
    prevents API keys and other secrets from leaking into sandboxed
    child processes.

    When ``config.allow_network`` is False, sets proxy environment
    variables to a dead address as a best-effort network block
    (raw sockets bypass this — full enforcement requires Docker sandbox).

    Args:
        config: Sandbox configuration.
        extra: Optional caller-supplied env vars (e.g. from execute_python).

    Returns:
        A dict suitable for passing as ``env`` to ``asyncio.create_subprocess_exec``.
    """
    env: dict[str, str] = {}
    for key in _ALLOWLISTED_ENV_VARS:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val

    # Config-declared env_vars override allowlist defaults
    env.update(config.env_vars)

    # Caller-supplied vars overlay everything
    if extra:
        env.update(extra)

    # Network gating: best-effort proxy blockade when network is disabled
    if not config.allow_network:
        env["HTTP_PROXY"] = "http://127.0.0.1:9"
        env["HTTPS_PROXY"] = "http://127.0.0.1:9"
        env["ALL_PROXY"] = "http://127.0.0.1:9"
        env["NO_PROXY"] = ""
        # Also set lowercase variants for tools that check those
        env["http_proxy"] = "http://127.0.0.1:9"
        env["https_proxy"] = "http://127.0.0.1:9"
        env["all_proxy"] = "http://127.0.0.1:9"
        env["no_proxy"] = ""

    return env


# ---------------------------------------------------------------------------
# Memory monitor (internal)
# ---------------------------------------------------------------------------


def _psutil_memory_monitor(
    pid: int, limit_bytes: int, stop_event: threading.Event, killed_flag: list[bool]
) -> None:
    """Background thread: kill process if RSS exceeds limit_bytes."""
    try:
        import psutil

        proc = psutil.Process(pid)
        while not stop_event.wait(timeout=0.5):
            try:
                if proc.memory_info().rss > limit_bytes:
                    proc.kill()
                    killed_flag[0] = True
                    return
            except psutil.NoSuchProcess:
                return
    except Exception:
        pass


class NativeWindowsSandbox(SandboxPort):
    """Sandbox implementation using native Windows process execution.

    **SECURITY NOTE:** This is a resource-limit wrapper, not a security
    boundary.  It enforces timeouts, memory limits, and output truncation,
    but it does NOT provide full process isolation (the child shares the
    parent's user account and can access the same filesystem).
    For true isolation, use ``DockerLinuxSandbox``.
    """

    _TRUNCATION_SUFFIX = b"...[truncated]"

    def __init__(self, config: SandboxConfig | None = None) -> None:
        """Initialize the sandbox with optional configuration.

        Args:
            config: Sandbox configuration. Uses defaults if None.
        """
        self._config = config or SandboxConfig()
        self._memory_limit_bytes: int | None = (
            self._config.memory_limit_mb * 1024 * 1024
            if self._config.memory_limit_mb is not None
            else None
        )

    @property
    def sandbox_type(self) -> SandboxType:
        """Return the type of this sandbox."""
        return SandboxType.NATIVE_WINDOWS

    async def is_available(self) -> bool:
        """Check if native Windows execution is available.

        Always returns True on Windows systems.
        """
        return sys.platform == "win32" or shutil.which("powershell") is not None

    def get_capabilities(self) -> set[SandboxCapability]:
        """Return capabilities supported by native Windows execution.

        NOTE: ``NETWORK_ACCESS`` reflects the configured value, not actual
        enforcement level.  Network blocking is best-effort (proxy vars only);
        raw sockets may still work.  Full enforcement requires Docker sandbox.
        """
        capabilities = {SandboxCapability.POWERSHELL, SandboxCapability.FILE_SYSTEM}

        # Check for Python
        if shutil.which("python") or shutil.which("python3"):
            capabilities.add(SandboxCapability.PYTHON)

        # Check for bash (Git Bash, Cygwin, etc.)
        if shutil.which("bash"):
            capabilities.add(SandboxCapability.BASH)

        # Network access is configurable
        if self._config.allow_network:
            capabilities.add(SandboxCapability.NETWORK_ACCESS)

        return capabilities

    async def execute(
        self,
        command: list[str],
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        """Execute a command with resource limits.

        Args:
            command: Command list to execute.
            timeout: Timeout in seconds. Uses config default if None.
            cwd: Working directory.
            env: Additional environment variables.
            memory_limit_mb: Optional memory limit override.

        Returns:
            SandboxResult with execution details.
        """
        timeout = timeout or self._config.timeout

        if timeout <= 0:
            return SandboxResult(
                stdout="",
                stderr=f"Invalid timeout {timeout!r}: must be > 0 seconds.",
                returncode=-1,
                elapsed_ms=0.0,
                sandbox_type=self.sandbox_type,
            )

        # Build child environment from minimal allowlist (never inherit secrets)
        merged_env = _build_child_env(self._config, env)

        # Determine working directory
        working_dir = cwd or self._config.working_dir

        # Determine memory limit
        limit_bytes = (
            memory_limit_mb * 1024 * 1024
            if memory_limit_mb is not None
            else self._memory_limit_bytes
        )

        t_start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(working_dir) if working_dir is not None else None,
                env=merged_env if merged_env else None,
            )
        except Exception as e:
            return SandboxResult(
                stdout="",
                stderr=f"Failed to start process: {e}",
                returncode=-1,
                elapsed_ms=0.0,
                sandbox_type=self.sandbox_type,
            )

        # Optional memory monitor
        stop_event = threading.Event()
        memory_killed: list[bool] = [False]
        monitor_task: asyncio.Task | None = None

        if limit_bytes is not None:
            monitor_task = asyncio.create_task(
                asyncio.to_thread(
                    _psutil_memory_monitor, proc.pid, limit_bytes, stop_event, memory_killed
                )
            )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed_ms = (time.monotonic() - t_start) * 1000
            return SandboxResult(
                stdout="",
                stderr=f"Process killed after {timeout:.0f}s timeout.",
                returncode=-1,
                elapsed_ms=elapsed_ms,
                timed_out=True,
                sandbox_type=self.sandbox_type,
            )
        finally:
            stop_event.set()
            if monitor_task is not None:
                try:
                    await monitor_task
                except Exception:
                    pass

        elapsed_ms = (time.monotonic() - t_start) * 1000

        # Truncate output
        stdout_b = self._truncate(stdout_b)
        stderr_b = self._truncate(stderr_b)

        return SandboxResult(
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            returncode=proc.returncode if proc.returncode is not None else -1,
            elapsed_ms=elapsed_ms,
            memory_killed=memory_killed[0],
            sandbox_type=self.sandbox_type,
        )

    async def execute_shell(
        self,
        script: str,
        shell: str = "powershell",
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        """Execute a shell script.

        Args:
            script: Shell script to execute.
            shell: Shell type ("powershell", "cmd", "bash").
            timeout: Timeout in seconds.
            cwd: Working directory.
            env: Additional environment variables.
            memory_limit_mb: Optional memory limit override.

        Returns:
            SandboxResult with execution details.
        """
        if shell == "powershell":
            # REFINEMENT: PowerShell's mkdir (New-Item wrapper) doesn't support '-p'.
            # It is recursive by default if using -Force or just multiple levels.
            # We strip '-p ' or ' -p' to prevent "ERROR: A subdirectory or file -p already exists."
            import re

            script = re.sub(r"\bmkdir\s+-p\s+", "mkdir ", script)
            script = re.sub(r"\bmkdir\s+--parents\s+", "mkdir ", script)
            command = ["powershell", "-NoProfile", "-Command", script]
        elif shell == "cmd":
            command = ["cmd", "/c", script]
        elif shell == "bash":
            command = ["bash", "-c", script]
        else:
            return SandboxResult(
                stdout="",
                stderr=f"Unsupported shell: {shell}",
                returncode=-1,
                elapsed_ms=0.0,
                sandbox_type=self.sandbox_type,
            )

        return await self.execute(command, timeout, cwd, env, memory_limit_mb)

    async def execute_python(
        self,
        code: str,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> SandboxResult:
        """Execute Python code.

        Args:
            code: Python code to execute.
            timeout: Timeout in seconds.
            cwd: Working directory.
            env: Additional environment variables.
            memory_limit_mb: Optional memory limit override.

        Returns:
            SandboxResult with execution details.
        """
        python_exe = shutil.which("python") or shutil.which("python3")
        if not python_exe:
            return SandboxResult(
                stdout="",
                stderr="Python executable not found",
                returncode=-1,
                elapsed_ms=0.0,
                sandbox_type=self.sandbox_type,
            )

        command = [python_exe, "-c", code]
        return await self.execute(command, timeout, cwd, env, memory_limit_mb)

    def _truncate(self, data: bytes) -> bytes:
        """Truncate data to max_output_bytes."""
        max_bytes = self._config.max_output_bytes
        if len(data) <= max_bytes:
            return data
        return data[:max_bytes] + self._TRUNCATION_SUFFIX
