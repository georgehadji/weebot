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
    
    def _run(self, command: str) -> str:
        """Execute PowerShell command."""
        # Check if it's a diagnostic shortcut
        if command in self.DIAGNOSTIC_COMMANDS:
            command = self.DIAGNOSTIC_COMMANDS[command]
        
        # Security validation
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
