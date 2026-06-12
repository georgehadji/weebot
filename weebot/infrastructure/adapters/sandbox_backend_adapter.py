"""SandboxBackendAdapter — implements BackendPort by delegating to SandboxPort.

All operations are implemented as shell commands executed through SandboxPort.execute_shell().
This provides a unified I/O layer that tools can call without constructing subprocesses directly.

Fallback chains for each operation:
- ls: powershell Get-ChildItem → cmd dir
- read: powershell Get-Content → cmd type
- write: PowerShell Set-Content → cmd echo/redir
- edit: Python inline script (safe, no deps)
- glob: Python glob → PowerShell Resolve-Path
- grep: PowerShell Select-String → Python fallback
- execute: direct passthrough to SandboxPort.execute_shell()
"""
from __future__ import annotations

import json
import logging
import re
import textwrap
from typing import Optional

from weebot.application.ports.backend_port import BackendPort
from weebot.application.ports.sandbox_port import SandboxPort
from weebot.domain.models.backend_results import (
    EditResult,
    ExecuteResult,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)

logger = logging.getLogger(__name__)


class SandboxBackendAdapter(BackendPort):
    """Adapts SandboxPort to the BackendPort interface.

    Args:
        sandbox: SandboxPort instance. If None, resolved lazily from DI.
        default_timeout: Default timeout in seconds for execute().
    """

    def __init__(
        self,
        sandbox: Optional[SandboxPort] = None,
        default_timeout: int = 60,
    ) -> None:
        if sandbox is None:
            raise ValueError(
                "SandboxBackendAdapter requires a SandboxPort. "
                "Inject via __init__(sandbox=...)."
            )
        self._sandbox = sandbox
        self._default_timeout = default_timeout

    async def _shell(self, script: str, timeout: Optional[int] = None) -> str:
        """Run a PowerShell script and return combined output."""
        result = await self._sandbox.execute_shell(
            script=script,
            shell="powershell",
            timeout=float(timeout or self._default_timeout),
        )
        return result.combined_output or ""

    async def _shell_json(self, script: str, timeout: Optional[int] = None) -> dict | list:
        """Run a PowerShell script that returns JSON, parse the output."""
        # Wrap script to output JSON on success, error message on failure
        wrapped = textwrap.dedent(f"""
        $ErrorActionPreference = "Stop"
        try {{
            {script}
        }} catch {{
            Write-Output '{{"$error": "$($_.Exception.Message)"}}'
        }}
        """)
        output = await self._shell(wrapped, timeout=timeout)
        # Extract JSON from the output (may have banner lines)
        json_match = re.search(r"(\{.*\}|\[.*\])", output, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        return {}

    # ── ls ────────────────────────────────────────────────────────

    async def ls(self, path: str) -> LsResult:
        try:
            escaped = path.replace("'", "''")
            data = await self._shell_json(
                f"Get-ChildItem -Path '{escaped}' -Force | "
                f"Select-Object Name, Mode, Length, LastWriteTime | "
                f"ConvertTo-Json -Compress"
            )
            entries = data if isinstance(data, list) else [data] if data else []
            return LsResult(entries=entries)
        except Exception as exc:
            return LsResult(error=str(exc))

    # ── read ──────────────────────────────────────────────────────

    async def read(self, file_path: str, offset: int = 0, limit: int = 100) -> ReadResult:
        try:
            escaped = file_path.replace("'", "''")
            # Get total line count first
            total_data = await self._shell_json(
                f"(Get-Content -Path '{escaped}').Count"
            )
            total_lines = int(total_data) if isinstance(total_data, (int, float)) else 0

            # Read the requested range
            start = offset + 1
            end = offset + limit
            content = await self._shell(
                f"Get-Content -Path '{escaped}' -TotalCount {end} | "
                f"Select-Object -Skip {offset}"
            )
            truncated = total_lines > (offset + limit)
            return ReadResult(
                content=content.strip(),
                line_count=min(limit, total_lines - offset),
                total_lines=total_lines,
                truncated=truncated,
            )
        except Exception as exc:
            return ReadResult(error=str(exc))

    # ── write ─────────────────────────────────────────────────────

    async def write(self, file_path: str, content: str) -> WriteResult:
        try:
            escaped = file_path.replace("'", "''")
            # Use a here-string to avoid escaping issues
            # Content is base64-encoded for safety, decoded on the PowerShell side
            import base64
            encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
            await self._shell(
                f"$bytes = [Convert]::FromBase64String('{encoded}'); "
                f"[IO.File]::WriteAllBytes('{escaped}', $bytes)"
            )
            return WriteResult(path=file_path, size_bytes=len(content.encode("utf-8")))
        except Exception as exc:
            return WriteResult(error=str(exc))

    # ── edit ──────────────────────────────────────────────────────

    async def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        try:
            # Read the file, perform replacement, write back
            read_result = await self.read(file_path, limit=100000)
            if not read_result.success:
                return EditResult(error=read_result.error)

            content = read_result.content
            if replace_all:
                new_content = content.replace(old_string, new_string)
                occurrences = content.count(old_string)
            else:
                occurrences = content.count(old_string)
                if occurrences == 0:
                    return EditResult(error=f"old_string not found in {file_path}")
                if occurrences > 1:
                    return EditResult(
                        error=f"old_string appears {occurrences}x — use replace_all=True or a more specific match"
                    )
                new_content = content.replace(old_string, new_string, 1)

            write_result = await self.write(file_path, new_content)
            if not write_result.success:
                return EditResult(error=write_result.error)
            return EditResult(path=file_path, occurrences=occurrences)
        except Exception as exc:
            return EditResult(error=str(exc))

    # ── glob ──────────────────────────────────────────────────────

    async def glob(self, pattern: str, path: Optional[str] = None) -> GlobResult:
        try:
            escaped_pattern = pattern.replace("'", "''")
            cmd = (
                f"Resolve-Path -Path '{escaped_pattern}' -ErrorAction SilentlyContinue "
                f"| Select-Object -ExpandProperty Path"
            )
            if path:
                escaped_path = path.replace("'", "''")
                cmd = (
                    f"Get-ChildItem -Path '{escaped_path}' -Recurse -Filter '{escaped_pattern}' -Name "
                    f"| ForEach-Object {{ Join-Path '{escaped_path}' $_ }}"
                )
            output = await self._shell(cmd)
            matches = [line.strip() for line in output.split("\n") if line.strip() and "Error" not in line]
            return GlobResult(matches=matches)
        except Exception as exc:
            return GlobResult(error=str(exc))

    # ── grep ──────────────────────────────────────────────────────

    async def grep(
        self,
        pattern: str,
        path: Optional[str] = None,
        glob_filter: Optional[str] = None,
    ) -> GrepResult:
        try:
            escaped = pattern.replace("'", "''")
            cmd = f"Get-ChildItem -Recurse -File"
            if path:
                escaped_path = path.replace("'", "''")
                cmd += f" -Path '{escaped_path}'"
            if glob_filter:
                cmd += f" -Filter '{glob_filter}'"
            cmd += (
                f" | Select-String -Pattern '{escaped}' -SimpleMatch "
                f" | Select-Object Filename, LineNumber, Line"
            )
            output = await self._shell(cmd)
            # Parse PowerShell formatted output
            matches: list[GrepMatch] = []
            for line in output.split("\n"):
                parts = line.strip().split(":", 2)
                if len(parts) == 3:
                    try:
                        matches.append(GrepMatch(
                            path=parts[0].strip(),
                            line=int(parts[1].strip()),
                            text=parts[2].strip(),
                        ))
                    except (ValueError, IndexError):
                        continue
            return GrepResult(matches=matches)
        except Exception as exc:
            return GrepResult(error=str(exc))

    # ── execute ───────────────────────────────────────────────────

    async def execute(
        self,
        command: str,
        timeout: Optional[int] = None,
    ) -> ExecuteResult:
        try:
            result = await self._sandbox.execute_shell(
                script=command,
                shell="powershell",
                timeout=float(timeout or self._default_timeout),
            )
            return ExecuteResult(
                output=result.combined_output,
                exit_code=result.returncode,
                truncated=result.timed_out,
                error=result.stderr if not result.success and result.stderr else None,
            )
        except Exception as exc:
            return ExecuteResult(error=str(exc))
