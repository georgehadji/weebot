"""Install a dependency from a trusted package catalog.

This deliberately is not a general downloader or shell escape hatch. A package is a bare
catalog name, passed as an argv value to PyPI (pip), npm, or Windows Package Manager
(winget). URLs, VCS specs, local paths, GitHub shorthands and installer scripts are refused
by the name check, and the commands are built to run no package code at install time.
Installing always asks first (`tool_guards._ALWAYS_ASK_TOOLS`), and every attempt is logged.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import Any, ClassVar

from pydantic import PrivateAttr

from weebot.config.tool_config import DEFAULT_TOOL_CONFIG, ToolConfig
from weebot.domain.models.output_trust import OutputTrust
from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# One shape per catalog. None allows ":", "/" (except an npm scope) or "+", which is what
# turns "git+https://...", "user/repo", "file:../x" and "C:/dir" into something else than a name.
_NAME_RE = {
    "pypi": re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*"),
    "npm": re.compile(r"(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*"),
    "winget": re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*"),
}
_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_TIMEOUT_S = 300


def _in_virtualenv() -> bool:
    return sys.prefix != sys.base_prefix


class ToolInstaller(BaseTool):
    """Install a package from PyPI, npm, or winget."""

    name: str = "install_tool"
    description: str = (
        "Install a missing dependency from a trusted catalog only: PyPI (source=pypi, "
        "prebuilt wheels), npm (source=npm) or Windows Package Manager (source=winget). "
        "Give the catalog name, not a URL or path. This action always needs user approval. "
        "Arbitrary URLs, shell commands, and remote installer scripts are not accepted."
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
    # The installer's output relays text from a package catalog, which a package author wrote.
    output_trust: ClassVar[OutputTrust] = OutputTrust.EXTERNAL

    _tool_config: ToolConfig | None = PrivateAttr(default=None)

    def set_config(self, config: ToolConfig) -> None:
        self._tool_config = config

    async def execute(self, source: str = "", package: str = "", **kwargs: Any) -> ToolResult:
        if not (self._tool_config or DEFAULT_TOOL_CONFIG).auto_install_tools:
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
        if source not in _NAME_RE:
            return ToolResult(output="", error="source must be pypi, npm, or winget")
        if not _NAME_RE[source].fullmatch(package):
            return ToolResult(output="", error=f"{package!r} is not a {source} catalog name")
        if version and not _VERSION_RE.fullmatch(version):
            return ToolResult(output="", error=f"{version!r} is not a catalog version")

        argv = self._command(source, package, version)
        if argv is None:
            return ToolResult(output="", error=f"{source} is not available on this machine")
        logger.info("install_tool: %s %s %s", source, package, version or "(latest)")
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except OSError as exc:
            logger.warning("install_tool: could not start %s: %s", source, exc)
            return ToolResult(output="", error=f"Could not start {source}: {exc}")
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_S)
        except TimeoutError:
            proc.kill()
            logger.warning("install_tool: %s %s timed out", source, package)
            return ToolResult(output="", error=f"{source} install timed out after {_TIMEOUT_S}s")

        detail = (out + err).decode("utf-8", errors="replace").strip()[-4_000:]
        if proc.returncode:
            logger.warning("install_tool: %s %s failed (exit %s)", source, package, proc.returncode)
            return ToolResult(
                output="", error=f"{source} install failed (exit {proc.returncode}): {detail}"
            )
        logger.info("install_tool: installed %s %s from %s", package, version or "(latest)", source)
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
            # Wheels only: a source distribution runs its setup.py while installing.
            # Inside a virtualenv, --user is an error and the venv is the right target.
            user = [] if _in_virtualenv() else ["--user"]
            return [
                sys.executable, "-m", "pip", "install", *user,
                "--disable-pip-version-check", "--only-binary=:all:", spec,
            ]
        if source == "npm":
            npm = "npm.cmd" if sys.platform == "win32" else "npm"
            prefix = Path.home() / ".weebot" / "tools" / "npm"
            spec = f"{package}@{version}" if version else package
            return [npm, "install", "--global", "--prefix", str(prefix), "--ignore-scripts", spec]
        if source == "winget" and sys.platform == "win32":
            command = [
                "winget", "install", "--exact", "--id", package, "--source", "winget",
                "--scope", "user", "--accept-package-agreements", "--accept-source-agreements",
            ]
            return [*command, "--version", version] if version else command
        return None
