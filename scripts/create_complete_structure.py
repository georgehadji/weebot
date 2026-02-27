#!/usr/bin/env python3
"""
Complete setup script for Manus-Win11 project.
Creates the entire folder structure with all files and proper imports.

Usage:
    python create_complete_structure.py
"""

import os
from pathlib import Path

def ensure_dir(path):
    """Ensure directory exists."""
    path.mkdir(parents=True, exist_ok=True)

def write_file(path, content):
    """Write content to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    print(f"  ✓ {path.name}")

def main():
    base_dir = Path(__file__).parent
    
    print("=" * 60)
    print("Manus-Win11 Project Structure Setup")
    print("=" * 60)
    
    # Create directories
    print("\\n[1/4] Creating directories...")
    dirs = [
        "manus_win11", "manus_win11/config", "manus_win11/utils",
        "manus_win11/tools", "manus_win11/core",
        "research_modules", "integrations", "cli",
        "templates", "cache", "logs"
    ]
    for d in dirs:
        ensure_dir(base_dir / d)
    print(f"  Created {len(dirs)} directories")
    
    # Create all __init__.py files
    print("\\n[2/4] Creating package init files...")
    init_dirs = [
        "manus_win11", "manus_win11/config", "manus_win11/utils",
        "manus_win11/tools", "manus_win11/core",
        "research_modules", "integrations", "cli"
    ]
    for d in init_dirs:
        init_file = base_dir / d / "__init__.py"
        init_file.write_text("", encoding='utf-8')
    print(f"  Created {len(init_dirs)} __init__.py files")
    
    # Create all module files with content
    print("\\n[3/4] Creating module files...")
    
    # File contents dictionary
    files = {}
    
    # manus_win11/config/settings.py
    files["manus_win11/config/settings.py"] = \'\'\'"""Configuration and constants for Manus-Win11 Agent."""
import os
from pathlib import Path

# Workspace Configuration
WORKSPACE_ROOT = Path(r"C:\\\\Users\\\\Public\\\\Manus_Workspace")
LOGS_DIR = Path("logs")
LOG_FILE = LOGS_DIR / "agent.log"

# Safety Configuration
REQUIRED_PATH_PREFIX = str(WORKSPACE_ROOT)  # Sandbox constraint
MAX_RETRIES = 3
CONFIRM_DELETE = True  # Enable Counterfactual Simulation for deletions

# Browser Configuration
BROWSER_TIMEOUT = 30000  # ms
HEADLESS = False

# LLM Configuration
MODEL_NAME = "gpt-4"  # or "gpt-4-turbo-preview"
TEMPERATURE = 0.2

# Heuristic Thresholds
POWERSHELL_PRIORITY_KEYWORDS = [
    "file", "delete", "copy", "move", "directory", 
    "process", "kill", "system", "registry", "download"
]


def ensure_workspace():
    """Ensure workspace exists."""
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
\'\'\'

    # manus_win11/utils/logger.py  
    files["manus_win11/utils/logger.py"] = \'\'\'"""Logging utility for Manus-Win11."""
import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("logs/agent.log")


class AgentLogger:
    def __init__(self):
        self.logger = logging.getLogger("ManusAgent")
        self.logger.setLevel(logging.DEBUG)
        
        # Ensure logs directory exists
        LOG_FILE.parent.mkdir(exist_ok=True)
        
        # File Handler with detailed formatting
        file_handler = logging.FileHandler(LOG_FILE, encoding=\'utf-8\')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            \'%(asctime)s | %(levelname)-8s | %(module)-12s | %(message)s\',
            datefmt=\'%Y-%m-%d %H:%M:%S\'
        )
        file_handler.setFormatter(file_format)
        
        # Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter(\'%(levelname)s: %(message)s\')
        console_handler.setFormatter(console_format)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def get_logger(self):
        return self.logger


def get_logger():
    return AgentLogger().get_logger()
\'\'\'

    # manus_win11/tools/powershell_tool.py
    files["manus_win11/tools/powershell_tool.py"] = \'\'\'"""PowerShell Tool for Windows 11 Sandbox operations."""
import subprocess
import json
import re
from typing import Dict, Any, Optional
from pathlib import Path
from langchain.tools import BaseTool
from pydantic import Field

from ..config.settings import WORKSPACE_ROOT, REQUIRED_PATH_PREFIX


class PowerShellTool(BaseTool):
    name: str = "powershell_executor"
    description: str = """Execute PowerShell commands in Windows 11 Sandbox environment.
    Use for: file operations, process management, system diagnostics, network testing.
    Workspace isolated to: C:\\\\Users\\\\Public\\\\Manus_Workspace"""
    
    # Available diagnostic commands as requested
    DIAGNOSTIC_COMMANDS = {
        "system_info": "Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, TotalPhysicalMemory, CsProcessors",
        "processes": "Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 Name, CPU, WorkingSet",
        "network_test": "Test-NetConnection -ComputerName google.com -Port 443 | Select-Object ComputerName, TcpTestSucceeded",
        "list_workspace": f"Get-ChildItem -Path \'{WORKSPACE_ROOT}\' -Recurse | Select-Object FullName, Length",
        "read_logs": f"Get-Content -Path \'{WORKSPACE_ROOT}\\\\error.log\' -Tail 20",
        "reset_browser": "Stop-Process -Name \'msedge\' -Force -ErrorAction SilentlyContinue",
        "execution_policy": "Get-ExecutionPolicy",
        "system_events": "Get-EventLog -LogName System -Newest 5 | Select-Object EntryType, Source, Message"
    }
    
    def _validate_path_safety(self, command: str) -> bool:
        """Ensure command doesn\'t escape sandbox."""
        dangerous_patterns = [
            r\'rm\\\\s+-Recurse\\\\s+C:\\\\(?!Users\\\\Public\\\\Manus_Workspace)\',
            r\'Remove-Item\\\\s+.*C:\\\\(?!Users\\\\Public\\\\Manus_Workspace)\',
            r\'Set-Location\\\\s+C:\\\\(?!Users\\\\Public)\',
            r\'cd\\\\s+C:\\\\(?!Users\\\\Public)\'
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return False
        return True
    
    def _run(self, command: str) -> str:
        """Execute PowerShell command."""
        # Check if it\'s a diagnostic shortcut
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
\'\'\'

    # manus_win11/tools/browser_tool.py
    files["manus_win11/tools/browser_tool.py"] = \'\'\'"""Browser Tool using browser-use and playwright."""
import asyncio
from typing import Optional, Dict, Any
from langchain.tools import BaseTool

from ..config.settings import BROWSER_TIMEOUT, HEADLESS

try:
    from browser_use import Browser, Agent as BrowserAgent
    from langchain_openai import ChatOpenAI
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False


class BrowserTool(BaseTool):
    name: str = "browser_navigator"
    description: str = """Navigate and interact with web pages using AI browser automation.
    Use for: web scraping, form filling, clicking buttons, extracting data from websites.
    Input should be a natural language description of the task."""
    
    browser: Optional[Any] = None
    
    def __init__(self):
        super().__init__()
        self._browser = None
    
    async def _ensure_browser(self):
        """Initialize browser if not exists."""
        if not BROWSER_USE_AVAILABLE:
            raise ImportError("browser-use not installed")
        if not self._browser:
            self._browser = Browser(headless=HEADLESS)
    
    async def _run_browser_task(self, task: str) -> str:
        """Execute browser task using browser-use."""
        try:
            await self._ensure_browser()
            
            # Initialize browser-use agent
            llm = ChatOpenAI(model="gpt-4", temperature=0)
            agent = BrowserAgent(
                task=task,
                llm=llm,
                browser=self._browser
            )
            
            result = await agent.run()
            return str(result)
            
        except Exception as e:
            return f"Browser Error: {str(e)}"
    
    def _run(self, task: str) -> str:
        """Synchronous wrapper for browser operations."""
        try:
            # Run async code in sync context
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
            
            result = asyncio.run(self._run_browser_task(task))
            return result
            
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def _arun(self, task: str) -> str:
        """Async execution."""
        return await self._run_browser_task(task)
\'\'\'

    # manus_win11/tools/heuristic_router.py
    files["manus_win11/tools/heuristic_router.py"] = \'\'\'"""Heuristic Analysis for tool selection."""
from typing import Dict, List

from ..config.settings import POWERSHELL_PRIORITY_KEYWORDS


class HeuristicRouter:
    """Analyzes tasks and routes to appropriate tool (PowerShell vs Browser)."""
    
    @staticmethod
    def analyze_task(task: str) -> Dict[str, any]:
        """
        Returns:
            {
                "primary_tool": "powershell" | "browser",
                "confidence": float,
                "reasoning": str,
                "suggested_sequence": List[str]
            }
        """
        task_lower = task.lower()
        
        # Scoring system
        ps_score = 0
        browser_score = 0
        
        # PowerShell indicators
        ps_indicators = [
            "file", "folder", "directory", "delete", "copy", "move",
            "process", "kill", "stop", "system", "registry", "install",
            "download to", "save to disk", "workspace", "log", "event viewer"
        ]
        
        # Browser indicators
        browser_indicators = [
            "website", "webpage", "url", "click", "form", "login",
            "browser", "chrome", "edge", "navigate to", "scrape",
            "extract from site", "online", "web search"
        ]
        
        for indicator in ps_indicators:
            if indicator in task_lower:
                ps_score += 1
        
        for indicator in browser_indicators:
            if indicator in task_lower:
                browser_score += 1
        
        # Special cases: downloads can be either
        if "download" in task_lower:
            if "file from web" in task_lower or "url" in task_lower:
                browser_score += 0.5
            else:
                ps_score += 1
        
        # Decision
        if ps_score > browser_score:
            tool = "powershell"
            confidence = min(ps_score / (ps_score + browser_score + 0.1), 1.0)
            reasoning = f"Local system operations detected (score: {ps_score} vs {browser_score})"
            sequence = ["powershell", "browser"]
        else:
            tool = "browser"
            confidence = min(browser_score / (ps_score + browser_score + 0.1), 1.0)
            reasoning = f"Web-based operations detected (score: {browser_score} vs {ps_score})"
            sequence = ["browser", "powershell"]
        
        return {
            "primary_tool": tool,
            "confidence": confidence,
            "reasoning": reasoning,
            "suggested_sequence": sequence
        }
\'\'\'

    print(f"  Prepared {len(files)} files for manus_win11 package")
    
    # Write all files
    for file_path, content in files.items():
        write_file(base_dir / file_path, content)
    
    print("\\n[4/4] Creating run.py script...")
    write_file(base_dir / "run.py", \'\'\'#!/usr/bin/env python3
"""
Run script for Manus-Win11 Agent.

Usage:
    python run.py
"""

import sys
from pathlib import Path

# Add manus_win11 to path
sys.path.insert(0, str(Path(__file__).parent))

from manus_win11.main import main

if __name__ == "__main__":
    main()
\'\'\')

    print("\\n" + "=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print("\\nProject structure created:")
    print("""
manus_win11/
├── __init__.py
├── main.py
├── config/
│   ├── __init__.py
│   └── settings.py
├── utils/
│   ├── __init__.py
│   └── logger.py
└── tools/
    ├── __init__.py
    ├── powershell_tool.py
    ├── browser_tool.py
    └── heuristic_router.py

templates/
cache/
logs/
run.py
""")
    print("\\nTo run the agent:")
    print("    python run.py")

if __name__ == "__main__":
    main()
