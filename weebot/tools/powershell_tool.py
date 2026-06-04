"""PowerShell Tool for Windows 11 Sandbox operations."""
import asyncio
import json
import re
from typing import ClassVar, Dict, Any, Optional
from pathlib import Path
from langchain.tools import BaseTool
from pydantic import Field

# Configuration — use the canonical workspace from settings so the
# PowerShell tool operates in the same directory as every other tool.
# Respects the WEEBOT_WORKSPACE environment variable.
from weebot.config.settings import WORKSPACE_ROOT as _WORKSPACE_ROOT


class PowerShellTool(BaseTool):
    name: str = "powershell_executor"
    description: str = """Execute PowerShell commands in Windows 11 Sandbox environment.
    Use for: file operations, process management, system diagnostics, network testing.
    Workspace is configured via WEEBOT_WORKSPACE env var (default: current directory).
    Pass 'timeout' in seconds (default: 30, max: 300)."""
    
    # Available diagnostic commands as requested
    DIAGNOSTIC_COMMANDS: ClassVar[Dict[str, str]] = {
        "system_info": "Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, TotalPhysicalMemory, CsProcessors",
        "processes": "Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 Name, CPU, WorkingSet",
        "network_test": "Test-NetConnection -ComputerName google.com -Port 443 | Select-Object ComputerName, TcpTestSucceeded",
        "list_workspace": f"Get-ChildItem -Path '{_WORKSPACE_ROOT}' -Recurse | Select-Object FullName, Length",
        "read_logs": f"Get-Content -Path '{_WORKSPACE_ROOT}\\error.log' -Tail 20",
        "reset_browser": "Stop-Process -Name 'msedge' -Force -ErrorAction SilentlyContinue",
        "execution_policy": "Get-ExecutionPolicy",
        "system_events": "Get-EventLog -LogName System -Newest 5 | Select-Object EntryType, Source, Message"
    }
    
    # PowerShell dangerous cmdlets and patterns
    DANGEROUS_PATTERNS: ClassVar[list] = [
        r'\bformat-volume\b',
        r'\bformat\s+[a-z]:',
        r'\bInvoke-Expression\b|\biex\b',
        r'\bInvoke-Command\b|\bicm\b',
        r'\bStart-Process\b.*-Credential',
        r'\bNew-LocalUser\b|\bSet-LocalUser\b',
        r'\bAdd-WindowsCapability\b|\bRemove-WindowsFeature\b',
    ]
    
    # Encoded command patterns (command injection vector)
    ENCODED_COMMAND_PATTERNS: ClassVar[list] = [
        r'-enc\s+\S+',  # -enc followed by base64
        r'-EncodedCommand\s+\S+',  # Full parameter name
        r'-e\s+[A-Za-z0-9+/]{100,}',  # Short form with base64-like content
    ]
    
    def _validate_path_safety(self, command: str) -> bool:
        """Ensure command doesn't access dangerous system paths."""
        # Block dangerous system paths but allow user directories
        dangerous_patterns = [
            r'rm\s+-Recurse\s+C:\\Windows',
            r'rm\s+-Recurse\s+C:\\Program\s+Files',
            r'Remove-Item\s+.*C:\\Windows',
            r'Remove-Item\s+.*C:\\Program\s+Files',
            r'Format-Volume',
            r'Clear-Disk',
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return False
        return True
    
    def _validate_no_encoded_commands(self, command: str) -> tuple[bool, str]:
        """
        Check for encoded PowerShell commands which are a common injection vector.
        
        Returns:
            (is_valid, error_message)
        """
        cmd_lower = command.lower()
        
        # Check for encoded command patterns
        for pattern in self.ENCODED_COMMAND_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, (
                    "Security Error: Encoded PowerShell commands are not allowed. "
                    "Use plain text commands only."
                )
        
        # Check for base64-like strings that could be encoded commands
        # Base64 encoding often has = padding and specific character set
        base64_pattern = r'[A-Za-z0-9+/]{50,}={0,2}'
        matches = re.findall(base64_pattern, command)
        for match in matches:
            # If it's long enough to be a script, block it
            if len(match) > 100:
                # Check if it decodes to PowerShell-like content
                try:
                    import base64
                    decoded = base64.b64decode(match).decode('utf-16-le', errors='ignore')
                    if any(keyword in decoded.lower() for keyword in ['powershell', 'invoke', 'iex', 'cmdlet']):
                        return False, (
                            "Security Error: Suspicious encoded content detected. "
                            "Use plain text commands only."
                        )
                except Exception:
                    pass
        
        # Check for dangerous cmdlets
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False, (
                    f"Security Error: Command contains restricted operation. "
                    f"Pattern matched: {pattern}"
                )
        
        return True, ""
    
    def _get_max_timeout(self) -> float:
        """Read max timeout from ToolConfig if injected, otherwise default 300."""
        if hasattr(self, '_tool_config') and self._tool_config is not None:
            return float(self._tool_config.max_tool_timeout)
        return 300.0

    async def _run_async(self, command: str, timeout: float = 30.0) -> str:
        """Execute PowerShell command with security validation (async)."""
        # Check if it's a diagnostic shortcut
        if command in self.DIAGNOSTIC_COMMANDS:
            command = self.DIAGNOSTIC_COMMANDS[command]

        # Security validation: encoded commands
        is_valid, error_msg = self._validate_no_encoded_commands(command)
        if not is_valid:
            return f"Error: {error_msg}"

        # Security validation: path safety
        if not self._validate_path_safety(command):
            return "Error: Command violates sandbox constraints"

        effective_timeout = min(float(timeout), self._get_max_timeout())

        try:
            ps_cmd = await self._find_powershell()
            proc = await asyncio.create_subprocess_exec(
                ps_cmd, "-NoProfile", "-Command", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=effective_timeout
                )
                stdout = stdout.decode("utf-8", errors="replace") if stdout else ""
                stderr = stderr.decode("utf-8", errors="replace") if stderr else ""
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"Error: Command timed out after {effective_timeout:.0f} seconds"

            if proc.returncode != 0:
                return f"Error: {stderr}"
            return stdout if stdout else "Success"

        except Exception as e:
            return f"Error: {str(e)}"
    
    async def _find_powershell(self) -> str:
        """Find the powershell executable path asynchronously."""
        import os as _os
        system_root = _os.environ.get('SystemRoot', 'C:\\Windows')
        paths = [
            _os.path.join(system_root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'),
            _os.path.join(system_root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'),
        ]
        for p in paths:
            if _os.path.exists(p):
                return p
        return "powershell.exe"
    
    def _run(self, command: str) -> str:
        """Synchronous execution — kept for backward compatibility.

        Delegates to the async implementation via asyncio.run().
        """
        try:
            return asyncio.run(self._run_async(command))
        except Exception as e:
            return f"Error: {str(e)}"

    async def _arun(self, command: str) -> str:
        """Async execution via the async _run method."""
        try:
            return await self._run_async(command)
        except Exception as e:
            return f"Error: {str(e)}"


# --- weebot BaseTool wrapper -------------------------------------------------
from pydantic import ConfigDict, PrivateAttr  # noqa: E402
from weebot.core.approval_policy import ExecApprovalPolicy  # noqa: E402
from weebot.application.ports.sandbox_port import SandboxPort
from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox
from weebot.tools.base import BaseTool as _WeebotBaseTool, ToolResult as _ToolResult  # noqa: E402


_POWERSHELL_DESC = (
    f"Execute a PowerShell command on Windows 11. "
    f"Working directory / workspace root: {_WORKSPACE_ROOT}. "
    "Accepts optional 'timeout' in seconds (default: 30, max: 300). "
    "Diagnostic shortcuts: system_info, processes, network_test, list_workspace."
)


class PowerShellBaseTool(_WeebotBaseTool):
    """weebot BaseTool wrapper around PowerShellTool for use in the ReAct agent."""

    name: str = "powershell"
    description: str = _POWERSHELL_DESC
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "PowerShell command or diagnostic shortcut to execute",
            }
        },
        "required": ["command"],
    }

    model_config = ConfigDict(arbitrary_types_allowed=True)
    _inner: PowerShellTool = PrivateAttr(default=None)
    _sandbox: SandboxPort = PrivateAttr(default=None)

    def model_post_init(self, __context) -> None:
        self._inner = PowerShellTool()
        self._sandbox = NativeWindowsSandbox()

    async def execute(self, command: str, timeout: Optional[float] = None, **_) -> _ToolResult:  # type: ignore[override]
        # Coerce timeout and apply ceiling
        try:
            effective_timeout = float(timeout) if timeout is not None else 30.0
        except (TypeError, ValueError):
            effective_timeout = 30.0
        ceiling = self._inner._get_max_timeout()
        effective_timeout = min(effective_timeout, ceiling)

        # ── Security validation (applies to BOTH paths) ──
        # Encoded command detection
        is_valid, error_msg = self._inner._validate_no_encoded_commands(command)
        if not is_valid:
            return _ToolResult(output="", error=error_msg)
        # Path safety validation
        if not self._inner._validate_path_safety(command):
            return _ToolResult(output="", error="Error: Command violates sandbox constraints")
        # Approval policy gate
        _policy = ExecApprovalPolicy()
        approval = _policy.evaluate(command)
        if not approval.approved:
            return _ToolResult(output="", error=f"Command denied by policy: {approval.reason}")
        if approval.requires_confirmation:
            return _ToolResult(
                output="",
                error=f"Command requires confirmation: {approval.undo_hint}",
            )

        # Route through SandboxPort (always via NativeWindowsSandbox)
        try:
            s_result = await self._sandbox.execute_shell(
                script=command,
                shell="powershell",
                timeout=effective_timeout,
            )
            if s_result.timed_out:
                return _ToolResult(output="", error=f"Command timed out after {effective_timeout:.0f}s")
            if not s_result.success and s_result.stderr:
                return _ToolResult(output=s_result.stdout, error=s_result.stderr)
            return _ToolResult(output=s_result.combined_output)
        except Exception as e:
            return _ToolResult(output="", error=str(e))
