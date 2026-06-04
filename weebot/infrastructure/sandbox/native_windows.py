"""NativeWindowsSandbox — Windows-native process execution with resource limits."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from weebot.application.ports.sandbox_port import (
    SandboxCapability,
    SandboxConfig,
    SandboxPort,
    SandboxResult,
    SandboxType,
)


# ---------------------------------------------------------------------------
# Memory monitor (internal)
# ---------------------------------------------------------------------------

def _psutil_memory_monitor(
    pid: int,
    limit_bytes: int,
    stop_event: threading.Event,
    killed_flag: list[bool],
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
    
    This is the default sandbox on Windows systems. It provides:
    - Timeout enforcement
    - Memory limits (with psutil)
    - Output truncation
    - PowerShell and CMD support
    
    Example:
        sandbox = NativeWindowsSandbox()
        result = await sandbox.execute(["python", "-c", "print('hello')"])
        print(result.stdout)
    """
    
    _TRUNCATION_SUFFIX = b"...[truncated]"
    
    def __init__(self, config: Optional[SandboxConfig] = None) -> None:
        """Initialize the sandbox with optional configuration.
        
        Args:
            config: Sandbox configuration. Uses defaults if None.
        """
        self._config = config or SandboxConfig()
        self._memory_limit_bytes: Optional[int] = (
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
        """Return capabilities supported by native Windows execution."""
        capabilities = {
            SandboxCapability.POWERSHELL,
            SandboxCapability.FILE_SYSTEM,
        }
        
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
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute a command with resource limits.
        
        Args:
            command: Command list to execute.
            timeout: Timeout in seconds. Uses config default if None.
            cwd: Working directory.
            env: Additional environment variables.
        
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
        
        # Merge environment variables
        merged_env = dict(self._config.env_vars)
        if env:
            merged_env.update(env)
        
        # Determine working directory
        working_dir = cwd or self._config.working_dir
        
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
        monitor_task: Optional[asyncio.Task] = None
        
        if self._memory_limit_bytes is not None:
            monitor_task = asyncio.create_task(
                asyncio.to_thread(
                    _psutil_memory_monitor,
                    proc.pid,
                    self._memory_limit_bytes,
                    stop_event,
                    memory_killed,
                )
            )
        
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
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
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute a shell script.
        
        Args:
            script: Shell script to execute.
            shell: Shell type ("powershell", "cmd", "bash").
            timeout: Timeout in seconds.
            cwd: Working directory.
            env: Additional environment variables.
        
        Returns:
            SandboxResult with execution details.
        """
        if shell == "powershell":
            # REFINEMENT: PowerShell's mkdir (New-Item wrapper) doesn't support '-p'.
            # It is recursive by default if using -Force or just multiple levels.
            # We strip '-p ' or ' -p' to prevent "ERROR: A subdirectory or file -p already exists."
            import re
            script = re.sub(r'\bmkdir\s+-p\s+', 'mkdir ', script)
            script = re.sub(r'\bmkdir\s+--parents\s+', 'mkdir ', script)
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
        
        return await self.execute(command, timeout, cwd, env)
    
    async def execute_python(
        self,
        code: str,
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute Python code.
        
        Args:
            code: Python code to execute.
            timeout: Timeout in seconds.
            cwd: Working directory.
            env: Additional environment variables.
        
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
        return await self.execute(command, timeout, cwd, env)
    
    def _truncate(self, data: bytes) -> bytes:
        """Truncate data to max_output_bytes."""
        max_bytes = self._config.max_output_bytes
        if len(data) <= max_bytes:
            return data
        return data[:max_bytes] + self._TRUNCATION_SUFFIX
