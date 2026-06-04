"""DockerLinuxSandbox — Docker container-based Linux execution."""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path, PurePath
from typing import Any, Optional

from weebot.application.ports.sandbox_port import (
    SandboxCapability,
    SandboxConfig,
    SandboxPort,
    SandboxResult,
    SandboxType,
)


class DockerLinuxSandbox(SandboxPort):
    """Sandbox implementation using Docker containers.
    
    This sandbox runs commands in isolated Docker containers, providing:
    - True process isolation
    - Resource limits (CPU, memory)
    - Network isolation (optional)
    - File system isolation with bind mounts
    
    Requires Docker to be installed and running.
    
    Example:
        config = SandboxConfig(
            timeout=60.0,
            memory_limit_mb=512,
            allow_network=False,
        )
        sandbox = DockerLinuxSandbox(config)
        if await sandbox.is_available():
            result = await sandbox.execute(["python", "-c", "print('hello')"])
            print(result.stdout)
    """
    
    _TRUNCATION_SUFFIX = b"...[truncated]"
    DEFAULT_IMAGE = "python:3.11-slim"
    CUSTOM_IMAGE = "weebot-tool-env:latest"
    
    def __init__(
        self,
        config: Optional[SandboxConfig] = None,
        image: Optional[str] = None,
        docker_path: Optional[str] = None,
    ) -> None:
        """Initialize the Docker sandbox.
        
        Args:
            config: Sandbox configuration. Uses defaults if None.
            image: Docker image to use. Defaults to python:3.11-slim.
            docker_path: Path to docker executable. Auto-detected if None.
        """
        self._config = config or SandboxConfig()
        self._image = image or self.DEFAULT_IMAGE
        self._docker_path = docker_path or shutil.which("docker") or "docker"
    
    async def _resolve_image(self) -> str:
        """Return the custom image if available, else fall back to DEFAULT_IMAGE.

        When an explicit *image* was passed to the constructor, it is used
        as-is.  When using the default, the builder-preferred
        ``weebot-tool-env:latest`` is tried first with a graceful fallback
        to ``python:3.11-slim``.
        """
        if self._image != self.DEFAULT_IMAGE:
            return self._image
        # Quick docker inspect to check for the custom image
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_path, "image", "inspect", self.CUSTOM_IMAGE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            if proc.returncode == 0:
                return self.CUSTOM_IMAGE
        except Exception:
            pass
        return self.DEFAULT_IMAGE

    @property
    def sandbox_type(self) -> SandboxType:
        """Return the type of this sandbox."""
        return SandboxType.DOCKER_LINUX
    
    async def is_available(self) -> bool:
        """Check if Docker is available and running."""
        if shutil.which("docker") is None:
            return False
        
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_path,
                "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            return proc.returncode == 0
        except Exception:
            return False
    
    def get_capabilities(self) -> set[SandboxCapability]:
        """Return capabilities supported by Docker."""
        capabilities = {
            SandboxCapability.BASH,
            SandboxCapability.PYTHON,
            SandboxCapability.FILE_SYSTEM,
        }
        
        if self._config.allow_network:
            capabilities.add(SandboxCapability.NETWORK_ACCESS)
        
        return capabilities
    
    async def _build_docker_command(
        self,
        command: list[str],
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
        memory_limit_mb: Optional[int] = None,
    ) -> list[str]:
        """Build the docker run command with all options.

        Resolves the effective image (custom → fallback) before building.
        """
        image = await self._resolve_image()
        docker_cmd = [
            self._docker_path,
            "run",
            "--rm",  # Remove container after execution
            "-i",    # Interactive
        ]
        
        # Memory limit
        limit = memory_limit_mb or self._config.memory_limit_mb
        if limit:
            docker_cmd.extend(["-m", f"{limit}m"])
        
        # Network
        if not self._config.allow_network:
            docker_cmd.extend(["--network", "none"])
        
        # Environment variables
        if env:
            for key, value in env.items():
                docker_cmd.extend(["-e", f"{key}={value}"])
        
        # Mount paths (sanitized against traversal)
        for ro_path in self._config.read_only_paths:
            if ".." in PurePath(str(ro_path)).parts:
                logger.warning("Blocked path traversal in ro_path: %s", ro_path)
                continue
            docker_cmd.extend([
                "-v",
                f"{ro_path}:{ro_path}:ro",
            ])
        
        for rw_path in self._config.read_write_paths:
            if ".." in PurePath(str(rw_path)).parts:
                logger.warning("Blocked path traversal in rw_path: %s", rw_path)
                continue
            docker_cmd.extend([
                "-v",
                f"{rw_path}:{rw_path}",
            ])
        
        # Working directory
        if cwd:
            docker_cmd.extend(["-w", str(cwd)])
        
        # Image and command
        docker_cmd.append(image)
        docker_cmd.extend(command)
        
        return docker_cmd
    
    async def execute(
        self,
        command: list[str],
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
        memory_limit_mb: Optional[int] = None,
    ) -> SandboxResult:
        """Execute a command in a Docker container.
        
        Args:
            command: Command list to execute.
            timeout: Timeout in seconds. Uses config default if None.
            cwd: Working directory inside container.
            env: Additional environment variables.
            memory_limit_mb: Optional memory limit in MB.
        
        Returns:
            SandboxResult with execution details.
        """
        if not await self.is_available():
            return SandboxResult(
                stdout="",
                stderr="Docker is not available on this system",
                returncode=-1,
                elapsed_ms=0.0,
                sandbox_type=self.sandbox_type,
            )
        
        timeout = timeout or self._config.timeout
        
        if timeout <= 0:
            return SandboxResult(
                stdout="",
                stderr=f"Invalid timeout {timeout!r}: must be > 0 seconds.",
                returncode=-1,
                elapsed_ms=0.0,
                sandbox_type=self.sandbox_type,
            )
        
        # Merge environment
        merged_env = dict(self._config.env_vars)
        if env:
            merged_env.update(env)
        
        # Build docker command (image resolved lazily)
        docker_command = await self._build_docker_command(command, cwd, merged_env, memory_limit_mb)
        
        import time
        t_start = time.monotonic()
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            
        except asyncio.TimeoutError:
            # Try to kill the container if it timed out
            # Note: The container should auto-remove due to --rm
            return SandboxResult(
                stdout="",
                stderr=f"Container killed after {timeout:.0f}s timeout.",
                returncode=-1,
                elapsed_ms=(time.monotonic() - t_start) * 1000,
                timed_out=True,
                sandbox_type=self.sandbox_type,
            )
        except Exception as e:
            return SandboxResult(
                stdout="",
                stderr=f"Failed to execute in Docker: {e}",
                returncode=-1,
                elapsed_ms=(time.monotonic() - t_start) * 1000,
                sandbox_type=self.sandbox_type,
            )
        
        elapsed_ms = (time.monotonic() - t_start) * 1000
        
        # Truncate output
        stdout_b = self._truncate(stdout_b)
        stderr_b = self._truncate(stderr_b)
        
        return SandboxResult(
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            returncode=proc.returncode if proc.returncode is not None else -1,
            elapsed_ms=elapsed_ms,
            sandbox_type=self.sandbox_type,
        )
    
    async def execute_shell(
        self,
        script: str,
        shell: str = "bash",
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
        memory_limit_mb: Optional[int] = None,
    ) -> SandboxResult:
        """Execute a shell script in Docker.
        
        Args:
            script: Shell script to execute.
            shell: Shell type ("bash", "sh").
            timeout: Timeout in seconds.
            cwd: Working directory.
            env: Additional environment variables.
            memory_limit_mb: Optional memory limit in MB.
        
        Returns:
            SandboxResult with execution details.
        """
        command = [shell, "-c", script]
        return await self.execute(command, timeout, cwd, env, memory_limit_mb)
    
    async def execute_python(
        self,
        code: str,
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
        memory_limit_mb: Optional[int] = None,
    ) -> SandboxResult:
        """Execute Python code in Docker.
        
        Args:
            code: Python code to execute.
            timeout: Timeout in seconds.
            cwd: Working directory.
            env: Additional environment variables.
            memory_limit_mb: Optional memory limit in MB.
        
        Returns:
            SandboxResult with execution details.
        """
        command = ["python", "-c", code]
        return await self.execute(command, timeout, cwd, env, memory_limit_mb)
    
    def _truncate(self, data: bytes) -> bytes:
        """Truncate data to max_output_bytes."""
        max_bytes = self._config.max_output_bytes
        if len(data) <= max_bytes:
            return data
        return data[:max_bytes] + self._TRUNCATION_SUFFIX
    
    async def pull_image(self) -> tuple[bool, str]:
        """Pull the Docker image.
        
        Returns:
            Tuple of (success, message).
        """
        if not await self.is_available():
            return False, "Docker is not available"
        
        image = await self._resolve_image()
        
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_path,
                "pull",
                image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=300.0
            )
            
            if proc.returncode == 0:
                return True, f"Successfully pulled {self._image}"
            else:
                error = stderr.decode("utf-8", errors="replace")[:500]
                return False, f"Failed to pull image: {error}"
        except asyncio.TimeoutError:
            return False, "Image pull timed out after 5 minutes"
        except Exception as e:
            return False, f"Error pulling image: {e}"
    
    async def list_images(self) -> list[dict[str, Any]]:
        """List available Docker images.
        
        Returns:
            List of image dictionaries with 'repository', 'tag', 'size'.
        """
        if not await self.is_available():
            return []
        
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_path,
                "images",
                "--format",
                "{{json .}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            
            images = []
            for line in stdout.decode("utf-8", errors="replace").strip().split("\n"):
                line = line.strip()
                if line:
                    try:
                        img = json.loads(line)
                        images.append({
                            "repository": img.get("Repository", ""),
                            "tag": img.get("Tag", ""),
                            "size": img.get("Size", ""),
                        })
                    except json.JSONDecodeError:
                        pass
            return images
        except Exception:
            return []
