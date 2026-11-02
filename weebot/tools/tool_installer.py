"""Install a dependency from a trusted package catalog.

This deliberately is not a general downloader or shell escape hatch. Package
names are passed as argv values to PyPI (pip), npm, or Windows Package Manager
(winget). Each installation remains subject to Weebot's approval flow.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import PrivateAttr

from weebot.config.tool_config import ToolConfig
from weebot.tools.base import BaseTool, ToolResult

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@/+:-]*$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!<>=~-]*$")
_TIMEOUT_S = 300


class ToolInstaller(BaseTool):
    """Install a package from PyPI, npm, or winget into the user environment."""

    name: str = "install_tool"
    description: str = (
        "Install a missing dependency from a trusted catalog only: PyPI (source=pypi), "
        "npm (source=npm), or Windows Package Manager (source=winget). This action "
        "always needs user approval. Arbitrary URLs, shell commands, and remote "
        "installer scripts are not accepted."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["pypi", "npm", "winget"]},
            "package": {"type": "string", "description": "Catalog package or app identifier"},
            "version": {"type": "string", "description": "Optional exact catalog version"},
        },
        "required": ["source", "package"],
    }
    default_timeout_seconds: int = _TIMEOUT_S + 10

    _tool_config: ToolConfig | None = PrivateAttr(default=None)

    def set_config(self, config: ToolConfig) -> None:
        self._tool_config = config

    async def execute(self, source: str = "", package: str = "", **kwargs: Any) -> ToolResult:
        if not (self._tool_config and self._tool_config.auto_install_tools):
            return ToolResult(
                output="",
                error=(
                    "Automatic dependency installation is disabled. Set "
                    "WEEBOT_AUTO_INSTALL_TOOLS=true to enable trusted-catalog installs."
                ),
            )
        source = source.lower().strip()
        package = package.strip()
        version = str(kwargs.get("version") or "").strip()
        if source not in {"pypi", "npm", "winget"}:
            return ToolResult(output="", error="source must be pypi, npm, or winget")
        valid_version = not version or _VERSION_RE.fullmatch(version)
        if not _PACKAGE_RE.fullmatch(package) or not valid_version:
            return ToolResult(output="", error="package or version contains unsupported characters")

        argv = self._command(source, package, version)
        if argv is None:
            return ToolResult(output="", error=f"{source} is not available on this machine")
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_S)
        except TimeoutError:
            proc.kill()
            return ToolResult(output="", error=f"{source} install timed out after {_TIMEOUT_S}s")
        except OSError as exc:
            return ToolResult(output="", error=f"Could not start {source}: {exc}")

        detail = (out + err).decode("utf-8", errors="replace").strip()[-4_000:]
        if proc.returncode:
            return ToolResult(
                output="", error=f"{source} install failed (exit {proc.returncode}): {detail}"
            )
        return ToolResult(
            output=(
                f"Installed {package}{'@' + version if version else ''} from {source}. "
                "The tool may need a new session or backend restart before it is discovered.\n"
                f"{detail}"
            )
        )

    @staticmethod
    def _command(source: str, package: str, version: str) -> list[str] | None:
        if source == "pypi":
            spec = f"{package}=={version}" if version else package
            return [
                sys.executable, "-m", "pip", "install", "--user", "--disable-pip-version-check", spec
            ]
        if source == "npm":
            npm = "npm.cmd" if sys.platform == "win32" else "npm"
            prefix = Path.home() / ".weebot" / "tools" / "npm"
            spec = f"{package}@{version}" if version else package
            return [npm, "install", "--global", "--prefix", str(prefix), "--ignore-scripts", spec]
        if source == "winget" and sys.platform == "win32":
            command = ["winget", "install", "--exact", "--id", package, "--scope", "user",
                       "--accept-package-agreements", "--accept-source-agreements"]
            return [*command, "--version", version] if version else command
        return None
