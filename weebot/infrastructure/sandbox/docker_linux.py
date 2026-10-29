"""DockerLinuxSandbox — Docker container-based Linux execution."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path, PurePath, PurePosixPath
from typing import Any

from weebot.infrastructure.adapters.platform_encoding import safe_decode
from weebot.application.ports.sandbox_port import (
    SandboxCapability,
    SandboxConfig,
    SandboxPort,
    SandboxResult,
    SandboxType,
    network_allowed,
)

logger = logging.getLogger(__name__)


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
    # ADR-014: the built tool image is required; it has the uid-1000 user.
    # python:3.11-slim was the fallback and ran everything as root.
    CUSTOM_IMAGE = "weebot-tool-env:latest"
    BUILD_HINT = (
        "docker build -t weebot-tool-env:latest -f docker/weebot-tool-env.Dockerfile ."
    )
    CONTAINER_WORKSPACE = "/workspace"
    SANDBOX_USER = "1000:1000"
    PIP_CACHE_VOLUME = "weebot-pip-cache"
    CONTAINER_PIP_CACHE = "/home/weebot/.cache/pip"

    def __init__(
        self,
        config: SandboxConfig | None = None,
        image: str | None = None,
        docker_path: str | None = None,
    ) -> None:
        """Initialize the Docker sandbox.

        Args:
            config: Sandbox configuration. Uses defaults if None.
            image: Docker image to use as-is. None means weebot-tool-env, required.
            docker_path: Path to docker executable. Auto-detected if None.
        """
        self._config = config or SandboxConfig()
        self._image = image
        self._docker_path = docker_path or shutil.which("docker") or "docker"

    async def _resolve_image(self) -> str | None:
        """The image to run, or None when weebot-tool-env is not built.

        An explicit *image* from the constructor is used as-is. Otherwise only
        ``weebot-tool-env:latest`` qualifies (ADR-014): it has the uid-1000 user
        that ``--user`` maps to.
        """
        if self._image:
            return self._image
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_path,
                "image",
                "inspect",
                self.CUSTOM_IMAGE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            if proc.returncode == 0:
                return self.CUSTOM_IMAGE
        except Exception as exc:
            logger.debug("docker image inspect failed: %r", exc)
        return None

    def _container_cwd(self, cwd: str | Path | None) -> str | None:
        """Map a host working directory into /workspace (ADR-014)."""
        workspace = self._config.workspace_dir
        if workspace is None:
            return str(cwd) if cwd else None
        if cwd:
            try:
                rel = Path(cwd).resolve().relative_to(Path(workspace).resolve())
                return str(PurePosixPath(self.CONTAINER_WORKSPACE, *rel.parts))
            except ValueError:
                logger.debug("cwd %s is outside the workspace; using /workspace", cwd)
        return self.CONTAINER_WORKSPACE

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
            SandboxCapability.NETWORK_ISOLATION,  # --network none is enforced
        }

        if self._config.allow_network:
            capabilities.add(SandboxCapability.NETWORK_ACCESS)

        return capabilities

    async def _build_docker_command(
        self,
        command: list[str],
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
    ) -> list[str]:
        """Build the docker run command with all options.

        Resolves the effective image (custom → fallback) before building.
        """
        image = await self._resolve_image()
        docker_cmd = [
            self._docker_path,
            "run",
            "--rm",  # Remove container after execution
            "-i",  # Interactive
            # Hardening (W3.9, F30; ADR-014): read-only root, not root, /tmp in
            # memory. pip installs land in /tmp/.local (PIP_USER) and reuse a
            # cache volume, so they work without a writable root filesystem.
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
            "--read-only",
            "--user",
            self.SANDBOX_USER,
            "--tmpfs",
            "/tmp:rw,exec,nosuid,size=256m",
            "-v",
            f"{self.PIP_CACHE_VOLUME}:{self.CONTAINER_PIP_CACHE}",
            "-e",
            "PIP_USER=1",
            "-e",
            "PYTHONUSERBASE=/tmp/.local",
            "-e",
            f"PIP_CACHE_DIR={self.CONTAINER_PIP_CACHE}",
        ]
        workspace = self._config.workspace_dir
        if workspace is not None:
            output = Path(workspace) / "Output"
            output.mkdir(parents=True, exist_ok=True)
            docker_cmd += ["-v", f"{workspace}:{self.CONTAINER_WORKSPACE}:ro"]
            docker_cmd += ["-v", f"{output}:{self.CONTAINER_WORKSPACE}/Output"]

        # Memory limit
        limit = memory_limit_mb or self._config.memory_limit_mb
        if limit:
            docker_cmd.extend(["-m", f"{limit}m"])

        # Network
        if not network_allowed(self._config):
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
            docker_cmd.extend(["-v", f"{ro_path}:{ro_path}:ro"])

        for rw_path in self._config.read_write_paths:
            if ".." in PurePath(str(rw_path)).parts:
                logger.warning("Blocked path traversal in rw_path: %s", rw_path)
                continue
            docker_cmd.extend(["-v", f"{rw_path}:{rw_path}"])

        # Working directory: the host path mapped into /workspace
        container_cwd = self._container_cwd(cwd)
        if container_cwd:
            docker_cmd.extend(["-w", container_cwd])

        # Image and command (execute() refuses first when the image is missing)
        docker_cmd.append(image or self.CUSTOM_IMAGE)
        docker_cmd.extend(command)

        return docker_cmd

    async def execute(
        self,
        command: list[str],
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
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

        if await self._resolve_image() is None:
            return SandboxResult(
                stdout="",
                stderr=(
                    f"Docker image {self.CUSTOM_IMAGE} is not built (ADR-014 requires it). "
                    f"Build it with: {self.BUILD_HINT}"
                ),
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
                *docker_command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        except TimeoutError:
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
            stdout=safe_decode(stdout_b),
            stderr=safe_decode(stderr_b),
            returncode=proc.returncode if proc.returncode is not None else -1,
            elapsed_ms=elapsed_ms,
            sandbox_type=self.sandbox_type,
        )

    async def execute_shell(
        self,
        script: str,
        shell: str = "bash",
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
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
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        memory_limit_mb: int | None = None,
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
        if image is None:
            # weebot-tool-env is built locally, not pulled from a registry.
            return False, f"{self.CUSTOM_IMAGE} is not built; run: {self.BUILD_HINT}"

        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_path,
                "pull",
                image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)

            if proc.returncode == 0:
                return True, f"Successfully pulled {image}"
            else:
                error = stderr.decode("utf-8", errors="replace")[:500]
                return False, f"Failed to pull image: {error}"
        except TimeoutError:
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
                        images.append(
                            {
                                "repository": img.get("Repository", ""),
                                "tag": img.get("Tag", ""),
                                "size": img.get("Size", ""),
                            }
                        )
                    except json.JSONDecodeError:
                        pass
            return images
        except Exception:
            return []
