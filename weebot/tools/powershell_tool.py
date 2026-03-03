"""PowerShell Tool for Windows 11 Sandbox operations."""
import subprocess
import json
import re
from typing import ClassVar, Dict, Any, Optional
from pathlib import Path
from langchain.tools import BaseTool
from pydantic import Field

# Configuration
WORKSPACE_ROOT = Path(r"C:\Users\Public\weebot_workspace")
REQUIRED_PATH_PREFIX = str(WORKSPACE_ROOT)


class PowerShellTool(BaseTool):
    name: str = "powershell_executor"
    description: str = """Execute PowerShell commands in Windows 11 Sandbox environment.
    Use for: file operations, process management, system diagnostics, network testing.
    Workspace isolated to: C:\\Users\\Public\\weebot_workspace"""
    
    # Available diagnostic commands as requested
    DIAGNOSTIC_COMMANDS: ClassVar[Dict[str, str]] = {
        "system_info": "Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, TotalPhysicalMemory, CsProcessors",
        "processes": "Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 Name, CPU, WorkingSet",
        "network_test": "Test-NetConnection -ComputerName google.com -Port 443 | Select-Object ComputerName, TcpTestSucceeded",
        "list_workspace": f"Get-ChildItem -Path '{WORKSPACE_ROOT}' -Recurse | Select-Object FullName, Length",
        "read_logs": f"Get-Content -Path '{WORKSPACE_ROOT}\\error.log' -Tail 20",
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
        """Ensure command doesn't escape sandbox."""
        dangerous_patterns = [
            r'rm\s+-Recurse\s+C:\\(?!Users\\Public\\weebot_workspace)',
            r'Remove-Item\s+.*C:\\(?!Users\\Public\\weebot_workspace)',
            r'Set-Location\s+C:\\(?!Users\\Public)',
            r'cd\s+C:\\(?!Users\\Public)'
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
    
    def _run(self, command: str) -> str:
        """Execute PowerShell command with security validation."""
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
        
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                cwd=str(WORKSPACE_ROOT),
                timeout=30
            )
            
            if result.returncode != 0:
                return f"Error: {result.stderr}"
            
            return result.stdout if result.stdout else "Success"
            
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds"
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def _arun(self, command: str) -> str:
        """Async execution."""
        return self._run(command)


# --- weebot BaseTool wrapper -------------------------------------------------
from pydantic import ConfigDict, PrivateAttr  # noqa: E402
from weebot.tools.base import BaseTool as _WeebotBaseTool, ToolResult as _ToolResult  # noqa: E402


class PowerShellBaseTool(_WeebotBaseTool):
    """weebot BaseTool wrapper around PowerShellTool for use in the ReAct agent."""

    name: str = "powershell"
    description: str = (
        "Execute a PowerShell command on Windows 11. "
        "Workspace isolated to C:\\\\Users\\\\Public\\\\weebot_workspace. "
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
    _inner: PowerShellTool = PrivateAttr(default=None)

    def model_post_init(self, __context) -> None:
        self._inner = PowerShellTool()

    async def execute(self, command: str, **_) -> _ToolResult:  # type: ignore[override]
        try:
            output = self._inner._run(command)
            if output.startswith("Error:"):
                return _ToolResult(output="", error=output)
            return _ToolResult(output=output)
        except Exception as e:
            return _ToolResult(output="", error=str(e))
