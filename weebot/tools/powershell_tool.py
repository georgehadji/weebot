"""PowerShell Tool for Windows 11 Sandbox operations.

Routes execution through SandboxPort.  No direct subprocess or langchain calls.
"""
from __future__ import annotations

import json
import re
from typing import ClassVar, Dict, Any, Optional

from pydantic import ConfigDict, PrivateAttr

from weebot.application.ports.sandbox_port import SandboxPort
from weebot.config.settings import WORKSPACE_ROOT as _WORKSPACE_ROOT
from weebot.config.tool_config import ToolConfig
from weebot.core.approval_policy import ExecApprovalPolicy
from weebot.tools.base import BaseTool, ToolResult


class PowerShellTool(BaseTool):
    """Execute PowerShell commands — routes through SandboxPort.

    Accepts optional 'timeout' in seconds (default: 30, max: 300).
    Diagnostic shortcuts: system_info, processes, network_test, list_workspace.
    """

    name: str = "powershell"
    description: str = (
        f"Execute a PowerShell command on Windows 11. "
        f"Working directory / workspace root: {_WORKSPACE_ROOT}. "
        "Accepts optional 'timeout' in seconds (default: 30, max: 300). "
        "Diagnostic shortcuts: system_info, processes, network_test, list_workspace."
    )
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
    _sandbox: SandboxPort = PrivateAttr()
    _tool_config: Optional[ToolConfig] = PrivateAttr(default=None)

    def __init__(self, sandbox: Optional[SandboxPort] = None,
                 tool_config: Optional[ToolConfig] = None):
        super().__init__()
        if sandbox is None:
            from weebot.application.di import Container
            c = Container()
            c.configure_defaults()
            sandbox = c.get(SandboxPort)
        self._sandbox = sandbox
        self._tool_config = tool_config

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
        if self._tool_config is not None:
            return float(self._tool_config.max_tool_timeout)
        return 300.0

    def _resolve_command(self, command: str) -> str:
        """Resolve diagnostic shortcut or pass through raw command."""
        return self.DIAGNOSTIC_COMMANDS.get(command, command)

    async def execute(self, command: str, timeout: Optional[float] = None, **_) -> ToolResult:  # type: ignore[override]
        # Resolve diagnostic shortcut
        command = self._resolve_command(command)

        # ── Security validation ──
        is_valid, error_msg = self._validate_no_encoded_commands(command)
        if not is_valid:
            return ToolResult(output="", error=error_msg)
        if not self._validate_path_safety(command):
            return ToolResult(output="", error="Error: Command violates sandbox constraints")

        # ── Approval policy gate ──
        policy = ExecApprovalPolicy()
        approval = policy.evaluate(command)
        if not approval.approved:
            return ToolResult(output="", error=f"Command denied by policy: {approval.reason}")
        if approval.requires_confirmation:
            return ToolResult(
                output="",
                error=f"Command requires confirmation: {approval.undo_hint}",
            )

        # Coerce and clamp timeout
        try:
            effective_timeout = min(float(timeout), self._get_max_timeout()) if timeout is not None else 30.0
        except (TypeError, ValueError):
            effective_timeout = 30.0

        # ── Route through SandboxPort (no direct subprocess) ──
        try:
            s_result = await self._sandbox.execute_shell(
                script=command,
                shell="powershell",
                timeout=effective_timeout,
            )
            if s_result.timed_out:
                return ToolResult(output="", error=f"Command timed out after {effective_timeout:.0f}s")
            if not s_result.success and s_result.stderr:
                return ToolResult(output=s_result.stdout, error=s_result.stderr)
            return ToolResult(output=s_result.combined_output)
        except Exception as e:
            return ToolResult(output="", error=str(e))
