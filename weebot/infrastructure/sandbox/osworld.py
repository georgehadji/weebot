"""OSWorldSandboxAdapter — KVM/Docker sandbox for OSWorld benchmark.

Communicates with a remote OSWorld VM instance via HTTP REST API or
runs commands in a local Docker container. Supports screenshot capture,
mouse/keyboard input relay, file transfer, and accessibility tree extraction.

Implementation follows the OSWorld environment protocol:
- Agent receives screenshots + a11y tree as observation
- Agent returns pyautogui-style actions (click, type, hotkey, scroll)
- Evaluation scripts verify task completion via file/state comparison
"""
from __future__ import annotations

import asyncio
import logging
import base64
import io
from pathlib import Path
from typing import Any, Optional

from weebot.application.ports.sandbox_port import (
    SandboxPort,
    SandboxType,
    SandboxCapability,
    SandboxResult,
    SandboxConfig,
)
from weebot.config.settings import OSWorldSettings

logger = logging.getLogger(__name__)

# Mimetypes for screenshot capture
_PNG_MIME = "image/png"
_JPEG_MIME = "image/jpeg"


class OSWorldConnectionError(Exception):
    """Raised when the OSWorld VM cannot be reached."""
    pass


class OSWorldSandboxAdapter(SandboxPort):
    """Sandbox adapter for OSWorld KVM/Docker benchmark VMs.

    Operates in two modes:
    - **remote**: Communicates with a KVM VM via HTTP REST API at
      ``http://<host>:<port>/``
    - **docker**: Runs commands in a local Docker container via the
      existing DockerLinuxSandbox infrastructure.

    The adapter relays screenshots, mouse/keyboard actions, and file
    transfers between the agent and the OSWorld environment.
    """

    def __init__(
        self,
        settings: OSWorldSettings | None = None,
        config: SandboxConfig | None = None,
    ) -> None:
        self._settings = settings or OSWorldSettings()
        self._config = config or SandboxConfig(allow_network=True)
        self._http_client: Any = None  # Lazy-init httpx client
        self._mode = self._settings.osworld_sandbox_type

    # ── Properties ─────────────────────────────────────────────────

    @property
    def sandbox_type(self) -> SandboxType:
        if self._mode == "docker":
            return SandboxType.DOCKER_LINUX
        return SandboxType.NATIVE_LINUX  # KVM/remote = Linux VM

    # ── Availability & capabilities ─────────────────────────────────

    async def is_available(self) -> bool:
        """Check whether the OSWorld VM is reachable."""
        if self._mode == "docker":
            return await self._check_docker_available()
        return await self._check_remote_available()

    def get_capabilities(self) -> set[SandboxCapability]:
        return {
            SandboxCapability.BASH,
            SandboxCapability.PYTHON,
            SandboxCapability.FILE_SYSTEM,
            SandboxCapability.NETWORK_ACCESS,
        }

    async def check_health(self) -> tuple[bool, str]:
        try:
            ok = await self.is_available()
            if ok:
                return True, f"OSWorld ({self._mode}) reachable at {self._settings.base_url}"
            return False, f"OSWorld ({self._mode}) not reachable at {self._settings.base_url}"
        except Exception as exc:
            return False, f"OSWorld health check failed: {exc}"

    # ── Command execution (SandboxPort contract) ────────────────────

    async def execute(
        self,
        command: list[str],
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
        memory_limit_mb: Optional[int] = None,
    ) -> SandboxResult:
        """Execute a command inside the OSWorld VM."""
        return await self._exec(command, timeout=timeout, cwd=cwd, env=env)

    async def execute_shell(
        self,
        script: str,
        shell: str = "bash",
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
        memory_limit_mb: Optional[int] = None,
    ) -> SandboxResult:
        """Execute a shell script inside the OSWorld VM."""
        return await self._exec(
            [shell, "-c", script],
            timeout=timeout, cwd=cwd, env=env,
        )

    async def execute_python(
        self,
        code: str,
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
        memory_limit_mb: Optional[int] = None,
    ) -> SandboxResult:
        """Execute Python code inside the OSWorld VM."""
        return await self._exec(
            ["python3", "-c", code],
            timeout=timeout, cwd=cwd, env=env,
        )

    # ── OSWorld-specific operations ─────────────────────────────────

    async def capture_screenshot(self) -> bytes:
        """Capture the current OSWorld VM screen as PNG bytes.

        Returns:
            Raw PNG image bytes suitable for base64 encoding.
        """
        if self._mode == "docker":
            return await self._docker_capture_screenshot()
        return await self._remote_capture_screenshot()

    async def click(self, x: int, y: int, button: str = "left") -> None:
        """Click at (x, y) in the OSWorld VM.

        Args:
            x: Horizontal pixel coordinate.
            y: Vertical pixel coordinate.
            button: Mouse button — "left", "right", or "middle".
        """
        import json
        payload = json.dumps({"action": "click", "x": x, "y": y, "button": button})
        await self._exec(["python3", "-c", f"""
import pyautogui
pyautogui.click({x}, {y}, button='{button}')
"""])

    async def double_click(self, x: int, y: int) -> None:
        """Double-click at (x, y)."""
        await self._exec(["python3", "-c", f"import pyautogui; pyautogui.doubleClick({x}, {y})"])

    async def type_text(self, text: str) -> None:
        """Type text into the currently focused element."""
        escaped = text.replace("'", "'\\''")
        await self._exec(["python3", "-c", f"import pyautogui; pyautogui.write('{escaped}', interval=0.05)"])

    async def hotkey(self, *keys: str) -> None:
        """Press a hotkey combination (e.g., hotkey('ctrl', 'c'))."""
        keys_str = ", ".join(f"'{k}'" for k in keys)
        await self._exec(["python3", "-c", f"import pyautogui; pyautogui.hotkey({keys_str})"])

    async def scroll(self, clicks: int, x: int | None = None, y: int | None = None) -> None:
        """Scroll at (x,y) or current position."""
        args = f"{x}, {y}, " if x is not None else ""
        await self._exec(["python3", "-c", f"import pyautogui; pyautogui.scroll({clicks}, {args}button='middle')"])

    async def get_accessibility_tree(self) -> str:
        """Fetch the accessibility tree from the OSWorld VM as a flat JSON array.

        Uses AT-SPI on Linux or UIA on Windows to enumerate interactive elements.
        Returns a JSON array of {name, role, bounds: {x,y,w,h}, enabled, focused}.
        """
        result = await self._exec(["python3", "-c", """
try:
    import pyatspi
    import json
    desktop = pyatspi.Registry.getDesktop(0)
    elements = []
    def walk(acc, depth=0):
        if depth > 15:
            return
        try:
            name = acc.name or ''
            role = acc.getRoleName()
            ext = acc.queryComponent().getExtents(0)
            debug_info = acc.get_attributes().get('accessible-roledescription', '')
            if role not in ('desktop', 'panel', 'separator', 'unknown'):
                elements.append({
                    'name': name[:80],
                    'role': role,
                    'bounds': {'x': ext.x, 'y': ext.y, 'w': ext.width, 'h': ext.height},
                    'enabled': True,
                    'focused': bool(acc.getState().contains(pyatspi.STATE_FOCUSED)),
                    'debug': debug_info[:40],
                })
        except (ImportError, Exception):
            pass
        try:
            for i in range(acc.getChildCount()):
                child = acc[i]
                if child:
                    walk(child, depth + 1)
        except Exception:
            pass
    walk(desktop)
    print(json.dumps(elements, ensure_ascii=False))
except ImportError:
    print(json.dumps([]))  # at-spi not available
"""])
        return result.stdout if result.success else "[]"

    async def get_file(self, remote_path: str) -> bytes:
        """Download a file from the OSWorld VM.

        Returns raw file contents.
        """
        if self._mode == "docker":
            result = await self._exec(["cat", remote_path])
            return result.stdout.encode()
        return await self._remote_get_file(remote_path)

    async def put_file(self, local_path: Path, remote_path: str) -> bool:
        """Upload a file to the OSWorld VM."""
        content = local_path.read_bytes()
        import json
        payload = json.dumps({"path": remote_path, "content": base64.b64encode(content).decode()})
        if self._mode == "remote":
            return await self._remote_put_file(remote_path, payload)
        # Docker: write via Python
        result = await self._exec(["python3", "-c", f"""
import base64
with open('{remote_path}', 'wb') as f:
    f.write(base64.b64decode({json.dumps(base64.b64encode(content).decode())}))
"""])
        return result.success

    # ── Internal implementations ────────────────────────────────────

    async def _check_docker_available(self) -> bool:
        from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox
        docker = DockerLinuxSandbox()
        return await docker.is_available()

    async def _check_remote_available(self) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._settings.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    async def _exec(
        self,
        cmd: list[str],
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute a command in the preferred backend."""
        import time as _t

        if self._mode == "docker":
            from weebot.infrastructure.sandbox.docker_linux import (
                DockerLinuxSandbox,
                SandboxResult as _SR,
            )
            docker = DockerLinuxSandbox()
            return await docker.execute(cmd, timeout=timeout, cwd=cwd, env=env)

        # Remote mode: execute via HTTP API
        return await self._remote_exec(cmd, timeout=timeout, cwd=cwd, env=env)

    async def _remote_exec(
        self,
        cmd: list[str],
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        import time as _t
        import json
        t0 = _t.monotonic()
        try:
            import httpx
            headers = {}
            if self._settings.osworld_api_token:
                headers["Authorization"] = f"Bearer {self._settings.osworld_api_token}"
            async with httpx.AsyncClient(timeout=self._settings.osworld_action_timeout) as client:
                resp = await client.post(
                    f"{self._settings.base_url}/execute",
                    json={"command": cmd, "cwd": str(cwd or ""), "env": env or {}},
                    headers=headers,
                )
                data = resp.json()
            elapsed = (_t.monotonic() - t0) * 1000
            return SandboxResult(
                stdout=data.get("stdout", ""),
                stderr=data.get("stderr", ""),
                returncode=data.get("returncode", -1),
                elapsed_ms=elapsed,
            )
        except Exception as exc:
            elapsed = (_t.monotonic() - t0) * 1000
            return SandboxResult(
                stdout="",
                stderr=str(exc),
                returncode=-1,
                elapsed_ms=elapsed,
            )

    async def _docker_capture_screenshot(self) -> bytes:
        """Capture screenshot from Docker container using import-display or scrot."""
        result = await self._exec([
            "python3", "-c",
            "import subprocess; subprocess.run(['import', '-window', 'root', '/tmp/screen.png'])",
        ])
        if result.success:
            file_result = await self._exec(["cat", "/tmp/screen.png"])
            return file_result.stdout.encode()
        raise OSWorldConnectionError("Docker screenshot capture failed")

    async def _remote_capture_screenshot(self) -> bytes:
        import httpx
        headers = {}
        if self._settings.osworld_api_token:
            headers["Authorization"] = f"Bearer {self._settings.osworld_api_token}"
        async with httpx.AsyncClient(timeout=self._settings.osworld_action_timeout) as client:
            resp = await client.get(
                f"{self._settings.base_url}/screenshot",
                headers=headers,
            )
            return resp.content

    async def _remote_get_file(self, remote_path: str) -> bytes:
        import httpx
        headers = {}
        if self._settings.osworld_api_token:
            headers["Authorization"] = f"Bearer {self._settings.osworld_api_token}"
        async with httpx.AsyncClient(timeout=self._settings.osworld_action_timeout) as client:
            resp = await client.get(
                f"{self._settings.base_url}/file",
                params={"path": remote_path},
                headers=headers,
            )
            return resp.content

    async def _remote_put_file(self, remote_path: str, payload: str) -> bool:
        import httpx
        headers = {}
        if self._settings.osworld_api_token:
            headers["Authorization"] = f"Bearer {self._settings.osworld_api_token}"
        try:
            async with httpx.AsyncClient(timeout=self._settings.osworld_action_timeout) as client:
                resp = await client.put(
                    f"{self._settings.base_url}/file?path={remote_path}",
                    content=payload,
                    headers=headers,
                )
                return resp.is_success
        except Exception:
            return False
