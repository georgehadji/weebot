"""Example 06 — Comprehensive Weebot Capabilities Showcase
==========================================================
Author: Georgios-Chrysovalantis Chatzivantsidis

A complete walkthrough of ALL weebot features in production scenarios:

  ✓ Agent Initialization & Configuration
  ✓ BashTool (PowerShell, system commands, git operations)
  ✓ PythonExecuteTool (sandboxed code execution with safety gates)
  ✓ WebSearchTool (DuckDuckGo/Bing research)
  ✓ StrReplaceEditorTool (file creation, editing, automation)
  ✓ AdvancedBrowserTool (Playwright automation, form filling, navigation)
  ✓ SchedulerTool (APScheduler cron/interval jobs)
  ✓ PlanningTool & PlanningFlow (ReAct reasoning)
  ✓ ComputerUseTool (mouse, keyboard, screen capture, OCR)
  ✓ StateManager (persistent tasks, messages, subsessions)
  ✓ ActivityStream (event tracking)
  ✓ Notifications (Telegram, Slack, Windows Toast, Logging)
  ✓ Safety & Approval Policies
  ✓ MCP Server Integration

This example demonstrates real-world usage patterns and best practices for:
  - Error handling and timeout protection
  - Async/await patterns for tool execution
  - Data processing pipelines
  - File automation workflows
  - Persistent state management
  - Event tracking and monitoring

Usage:
    python examples/06_comprehensive_capabilities_showcase.py

Requirements:
    - network access (for web search, browser automation)
    - optional: Telegram bot token, Slack webhook for notifications
    - optional: .env file with TELEGRAM_TOKEN, SLACK_WEBHOOK
\"\"\"
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# IMPORTS: Path setup and module imports
# ─────────────────────────────────────────────────────────────────────────────

# Configure Python path to allow running from project root
# This enables: python examples/06_comprehensive_capabilities_showcase.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")  # Enable UTF-8 output for terminal

# Core weebot imports
from weebot.activity_stream import ActivityStream  # Event tracking system
from weebot.config.settings import WeebotSettings  # Configuration management
from weebot.core.approval_policy import ApprovalMode, ExecApprovalPolicy  # Safety policies
from weebot.tools.bash_tool import BashTool  # System command execution
from weebot.tools.file_editor import StrReplaceEditorTool  # File operations
from weebot.tools.python_tool import PythonExecuteTool  # Sandboxed Python execution
from weebot.tools.web_search import WebSearchTool  # Research and web search
from weebot.state_manager import StateManager  # Persistent database storage
from weebot.domain.models import Task, Project  # Data models


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1: INITIALIZATION & CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════
# This section demonstrates how to properly initialize the weebot framework:
# - Load settings from environment variables or .env files
# - Initialize the activity stream for event tracking
# - Set up the state manager for persistent storage
# - Configure safety policies for code execution
# ═════════════════════════════════════════════════════════════════════════════

async def showcase_initialization() -> None:
    """
    Demonstrate agent setup, configuration, and settings management.
    
    This function shows how to:
    1. Load WeebotSettings from environment or .env file
    2. Initialize ActivityStream for tracking events (max 200 events)
    3. Set up StateManager with SQLite database for persistent storage
    4. Configure ExecApprovalPolicy for safety gate on code execution
    
    Returns:
        Tuple of (ActivityStream, StateManager) for use in other showcase functions
    """
    print("\n" + "=" * 80)
    print("SECTION 1: Initialization & Configuration")
    print("=" * 80)

    # ────────────────────────────────────────────────────────────────────────
    # Step 1.1: Load settings from environment
    # ────────────────────────────────────────────────────────────────────────
    # WeebotSettings uses pydantic-settings to load from:
    # - Environment variables (e.g., BASH_TIMEOUT=60)
    # - .env file in current directory
    # - Default values if not specified
    settings = WeebotSettings()
    print(f"✓ Settings loaded:")
    print(f"  - Log level: {settings.log_level}")
    print(f"  - Bash timeout: {settings.bash_timeout}s")
    print(f"  - Python timeout: {settings.python_timeout}s")
    print(f"  - Sandbox max output: {settings.sandbox_max_output_bytes // 1024} KB")
    print(f"  - Allow network: {settings.sandbox_allow_network}")
    print(f"  - Model: {settings.model_provider}")

    # ────────────────────────────────────────────────────────────────────────
    # Step 1.2: Initialize ActivityStream
    # ────────────────────────────────────────────────────────────────────────
    # ActivityStream is a ring buffer (deque) that tracks all agent activities.
    # It maintains a max of 200 events, automatically removing old ones.
    # Useful for monitoring, debugging, and event-driven workflows.
    stream = ActivityStream()
    stream.push("showcase-06", "system", "Initialization started")
    print(f"✓ Activity stream initialized (max {stream._maxlen} events)")

    # ────────────────────────────────────────────────────────────────────────
    # Step 1.3: Initialize StateManager with SQLite database
    # ────────────────────────────────────────────────────────────────────────
    # StateManager provides persistent storage for:
    # - Projects and Tasks (with SQLite backend)
    # - Messages and conversation history
    # - Sub-sessions for parallel work
    # Uses SQLite for reliability and cross-platform compatibility.
    db_path = Path(__file__).parent / "output" / "weebot_showcase.db"
    os.makedirs(db_path.parent, exist_ok=True)
    state_mgr = StateManager(db_path=str(db_path))
    print(f"✓ State manager initialized → {db_path}")

    # ────────────────────────────────────────────────────────────────────────
    # Step 1.4: Configure safety policy
    # ────────────────────────────────────────────────────────────────────────
    # ExecApprovalPolicy controls whether code execution is:
    # - AUTO: Allow all commands (development mode)
    # - ALWAYS_ASK: Require user confirmation for each command
    # - DENY: Reject all commands (safest mode)
    # This is a critical security gate for bash and python tools.
    policy = ExecApprovalPolicy(mode=ApprovalMode.AUTO)
    print(f"✓ Safety policy: {policy.mode.name} mode")

    return stream, state_mgr


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2: BASH TOOL — System Commands, Processes, Git
# ═════════════════════════════════════════════════════════════════════════════
# This section demonstrates the BashTool for executing system commands:
# - PowerShell commands on Windows
# - WSL2 bash commands for Linux compatibility
# - Git operations and repository management
# - System information queries
# - Process management and monitoring
# ═════════════════════════════════════════════════════════════════════════════

async def showcase_bash_tool(stream: ActivityStream) -> None:
    """
    Demonstrate BashTool for PowerShell/WSL commands, git, system tasks.
    
    This function demonstrates:
    1. Basic system information retrieval (PowerShell)
    2. Directory listing and file operations
    3. Git status and repository queries
    4. Environment checking (Python, pip packages)
    
    Note: BashTool supports both PowerShell (Windows) and WSL2 (Linux emulation)
    depending on the WeebotSettings and system availability.
    
    Args:
        stream: ActivityStream instance for event tracking
    """
    print("\n" + "=" * 80)
    print("SECTION 2: BashTool — System Commands & Automation")
    print("=" * 80)

    # Initialize BashTool with default settings
    bash = BashTool()

    # ────────────────────────────────────────────────────────────────────────
    # 2.1: Retrieve system information
    # ────────────────────────────────────────────────────────────────────────
    # Demonstrates PowerShell command execution for system diagnostics
    print("\n[2.1] Retrieving system information …")
    result = await bash.execute(
        command="powershell -NoProfile -Command \"Get-Host | Select Version\""
    )
    if not result.is_error:
        stream.push("showcase-06", "tool", "bash: system info")
        print(f"  ✅ {result.output[:200]}")
    else:
        print(f"  ❌ Error: {result.error}")

    # ────────────────────────────────────────────────────────────────────────
    # 2.2: List directory contents
    # ────────────────────────────────────────────────────────────────────────
    # Shows basic file system operations with piping and filtering
    print("\n[2.2] Listing current directory …")
    result = await bash.execute(command="ls -la | head -10")
    if not result.is_error:
        stream.push("showcase-06", "tool", "bash: directory listing")
        lines = result.output.split("\n")[:5]
        for line in lines:
            print(f"  {line}")
    else:
        print(f"  ❌ Error: {result.error}")

    # ────────────────────────────────────────────────────────────────────────
    # 2.3: Check git repository status
    # ────────────────────────────────────────────────────────────────────────
    # Demonstrates git integration for version control operations
    # This is useful for CI/CD pipelines, commit automation, etc.
    print("\n[2.3] Checking git repository status …")
    result = await bash.execute(command="git status --short")
    if not result.is_error:
        stream.push("showcase-06", "tool", "bash: git status")
        if result.output.strip():
            print(f"  Changes detected:\n{result.output[:400]}")
        else:
            print(f"  ✅ Working tree clean")
    else:
        print(f"  ❌ Error: {result.error}")

    # ────────────────────────────────────────────────────────────────────────
    # 2.4: Check Python environment
    # ────────────────────────────────────────────────────────────────────────
    # Verifies that required packages are installed and environment is ready
    # Important for ensuring dependencies are available before running code
    print("\n[2.4] Checking Python & environment …")
    result = await bash.execute(command="python --version && pip list | grep anthropic")
    if not result.is_error:
        stream.push("showcase-06", "tool", "bash: environment check")
        print(f"  ✅ {result.output[:200]}")
    else:
        print(f"  ❌ Error: {result.error}")


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3: PYTHON EXECUTION TOOL — Sandboxed Code with Safety Gates
# ═════════════════════════════════════════════════════════════════════════════
# This section demonstrates sandboxed Python execution with:
# - Process isolation (subprocess, not in-process eval)
# - Memory limits and monitoring
# - Timeout protection against infinite loops
# - Safety approval gates before execution
# - Output size limits to prevent context overflow
# ═════════════════════════════════════════════════════════════════════════════

async def showcase_python_tool(stream: ActivityStream) -> None:
    """
    Demonstrate PythonExecuteTool with isolation, memory limits, timeouts.
    
    This function shows:
    1. Mathematical computation and numeric processing
    2. Data analysis with pandas and numpy
    3. Timeout protection for long-running code
    
    Key features:
    - Code runs in isolated subprocess (not in-process eval)
    - 30-second timeout by default (configurable)
    - Memory usage monitoring (graceful degradation if psutil unavailable)
    - Output limited to 64 KB by default (prevents context overflow)
    - Results returned as ToolResult with stdout/stderr/returncode
    
    Args:
        stream: ActivityStream instance for event tracking
    """
    print("\n" + "=" * 80)
    print("SECTION 3: PythonExecuteTool — Sandboxed Execution")
    print("=" * 80)

    # Initialize the Python execution tool
    # This tool automatically handles isolation and safety checks
    python_tool = PythonExecuteTool()

    # ────────────────────────────────────────────────────────────────────────
    # 3.1: Simple mathematical computation
    # ────────────────────────────────────────────────────────────────────────
    # Demonstrates basic numeric operations and standard library usage
    print("\n[3.1] Running mathematical computation …")
    code = """
import math
result = sum([math.sqrt(i) for i in range(1, 101)])
print(f"Sum of square roots 1-100: {result:.2f}")
"""
    result = await python_tool.execute(code=code, timeout=10)
    if not result.is_error:
        stream.push("showcase-06", "tool", "python_execute: math")
        print(f"  ✅ {result.output.strip()}")
    else:
        print(f"  ❌ Error: {result.error}")

    # ────────────────────────────────────────────────────────────────────────
    # 3.2: Data processing with pandas
    # ────────────────────────────────────────────────────────────────────────
    # Shows data science workflow with:
    # - DataFrame creation and manipulation
    # - Statistical analysis (describe, groupby)
    # - Common data processing patterns
    # This is a typical use case for automated data analysis pipelines
    print("\n[3.2] Data processing (CSV analysis) …")
    code = """
import pandas as pd
import numpy as np

# Create sample data
data = {
    'date': pd.date_range('2026-01-01', periods=10),
    'value': np.random.randint(10, 100, 10),
    'category': ['A', 'B', 'C'] * 3 + ['A']
}
df = pd.DataFrame(data)

# Compute statistics
print("DataFrame shape:", df.shape)
print("\\nSummary stats:")
print(df[['value']].describe().to_string())
print("\\nBy category:")
print(df.groupby('category')['value'].mean())
"""
    result = await python_tool.execute(code=code, timeout=15)
    if not result.is_error:
        stream.push("showcase-06", "tool", "python_execute: data analysis")
        print(f"  ✅ Analysis output:\n{result.output[:500]}")
    else:
        print(f"  ❌ Error: {result.error}")

    # ────────────────────────────────────────────────────────────────────────
    # 3.3: Timeout demonstration
    # ────────────────────────────────────────────────────────────────────────
    # Shows how timeout protection works:
    # - Code that exceeds the timeout is interrupted
    # - Process is cleanly killed and error is returned
    # - Prevents runaway processes from hanging the agent
    print("\n[3.3] Demonstrating timeout protection …")
    code = "import time; time.sleep(35)  # Longer than default 30s timeout"
    result = await python_tool.execute(code=code, timeout=5)
    if result.is_error:
        stream.push("showcase-06", "tool", "python_execute: timeout test")
        print(f"  ✅ Timeout caught as expected: {result.error[:100]}")
    else:
        print(f"  ❌ Should have timed out!")


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4: WEB SEARCH — Research & Information Gathering
# ═════════════════════════════════════════════════════════════════════════════
# This section demonstrates web research capabilities:
# - DuckDuckGo search (primary, no API key required)
# - Bing search fallback (requires BING_API_KEY environment variable)
# - Research pipeline automation
# - Information gathering for decision support
# ═════════════════════════════════════════════════════════════════════════════

async def showcase_web_search(stream: ActivityStream) -> None:
    """
    Demonstrate WebSearchTool for research and information gathering.
    
    This function shows:
    1. Basic web search with DuckDuckGo
    2. Result parsing and preview
    3. Integration with other tools for analysis
    
    Note: Requires network access. If DuckDuckGo is unavailable,
    falls back to Bing (requires BING_API_KEY environment variable).
    
    Args:
        stream: ActivityStream instance for event tracking
    """
    print("\n" + "=" * 80)
    print("SECTION 4: WebSearchTool — Research & Gathering")
    print("=" * 80)

    # Initialize the web search tool
    # Automatically handles DuckDuckGo/Bing fallback
    search_tool = WebSearchTool()

    # ────────────────────────────────────────────────────────────────────────
    # 4.1: Technology research
    # ────────────────────────────────────────────────────────────────────────
    # Demonstrates typical research workflow for AI/ML topics
    # Results can be piped to python_tool for automated analysis
    print("\n[4.1] Searching for information …")
    result = await search_tool.execute(query="Claude AI model 2025", num_results=3)

    if not result.is_error:
        stream.push("showcase-06", "tool", "web_search: Claude AI")
        preview = result.output[:300].replace("\n", " ")
        print(f"  ✅ Found {len(result.output)} chars of content")
        print(f"  Preview: {preview}…")
    else:
        print(f"  ⚠️  Search unavailable: {result.error}")
        print(f"     (Network required; Bing API key optional for fallback)")


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5: FILE EDITOR — Create, Read, Edit, Automate
# ═════════════════════════════════════════════════════════════════════════════
# This section demonstrates file automation capabilities:
# - Creating new files (configuration, reports, documentation)
# - Reading and inspecting file contents
# - Find-and-replace editing of existing files
# - Markdown report generation
# - Automated documentation creation
# ═════════════════════════════════════════════════════════════════════════════

async def showcase_file_editor(stream: ActivityStream) -> None:
    """
    Demonstrate StrReplaceEditorTool for file operations.
    
    This function shows:
    1. Creating new configuration files (YAML)
    2. Reading file contents
    3. Editing files with find-and-replace
    4. Generating markdown reports
    
    The StrReplaceEditorTool supports:
    - create: Write new file with content
    - view: Read existing file
    - str_replace: Find and replace text
    - insert: Add lines at specific position
    
    Args:
        stream: ActivityStream instance for event tracking
    """
    print("\n" + "=" * 80)
    print("SECTION 5: StrReplaceEditorTool — File Automation")
    print("=" * 80)

    # Initialize the file editor tool
    editor = StrReplaceEditorTool()
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    # ────────────────────────────────────────────────────────────────────────
    # 5.1: Create a configuration file
    # ────────────────────────────────────────────────────────────────────────
    # Demonstrates creating structured configuration files in YAML format
    # Useful for agent setup, tool configuration, and workflow definitions
    print("\n[5.1] Creating a configuration file …")
    config_path = output_dir / "showcase_config.yaml"
    config_content = """# Weebot Showcase Configuration
# This file demonstrates configuration file creation via weebot
agent:
  name: "Showcase Agent"
  model: "claude-opus-4-6"
  timeout: 300
  budget: 10000

tools:
  enabled:
    - bash
    - python_execute
    - web_search
    - file_editor
    - browser_automation
    - scheduler

notifications:
  channels:
    - type: "log"
      level: "info"
"""
    result = await editor.execute(
        command="create", path=str(config_path), file_text=config_content
    )
    if not result.is_error:
        stream.push("showcase-06", "tool", f"file_editor: create config")
        print(f"  ✅ Created {config_path.name}")
    else:
        print(f"  ❌ Error: {result.error}")

    # ────────────────────────────────────────────────────────────────────────
    # 5.2: Read the created file
    # ────────────────────────────────────────────────────────────────────────
    # Verifies file creation and demonstrates file reading
    print("\n[5.2] Reading the created file …")
    result = await editor.execute(command="view", path=str(config_path))
    if not result.is_error:
        stream.push("showcase-06", "tool", "file_editor: view")
        lines = result.output.split("\n")[:5]
        for line in lines:
            print(f"  {line}")
    else:
        print(f"  ❌ Error: {result.error}")

    # ────────────────────────────────────────────────────────────────────────
    # 5.3: Edit the file
    # ────────────────────────────────────────────────────────────────────────
    # Shows find-and-replace functionality for file updates
    # This is the primary mechanism for programmatic file modification
    print("\n[5.3] Editing the file …")
    result = await editor.execute(
        command="str_replace",
        path=str(config_path),
        old_str='  timeout: 300',
        new_str='  timeout: 600  # Increased for complex tasks'
    )
    if not result.is_error:
        stream.push("showcase-06", "tool", "file_editor: str_replace")
        print(f"  ✅ Updated timeout setting")
    else:
        print(f"  ❌ Error: {result.error}")

    # ────────────────────────────────────────────────────────────────────────
    # 5.4: Create a markdown report
    # ────────────────────────────────────────────────────────────────────────
    # Demonstrates automated report generation with dynamic content
    # Useful for creating summaries, documentation, and audit trails
    print("\n[5.4] Generating markdown report …")
    report_path = output_dir / "showcase_report.md"
    report = f"""# Weebot Comprehensive Showcase Report
Generated: {datetime.now().isoformat()}

## Overview
This report demonstrates all capabilities of the weebot framework.

## Sections Executed
- ✅ Initialization & Configuration
- ✅ BashTool (system commands, git)
- ✅ PythonExecuteTool (sandboxed execution)
- ✅ WebSearchTool (research)
- ✅ FileEditorTool (file automation)
- ✅ AdvancedBrowserTool (automation)
- ✅ SchedulerTool (job scheduling)
- ✅ StateManager (persistence)
- ✅ ActivityStream (event tracking)
- ✅ Safety & Policies

## Key Features
1. **Multi-tool orchestration** - seamless integration across tools
2. **Safety gates** - approval policies for sensitive operations
3. **Persistent state** - SQLite-backed storage
4. **Event tracking** - real-time activity monitoring
5. **Error resilience** - timeout protection and graceful degradation
"""
    result = await editor.execute(
        command="create", path=str(report_path), file_text=report
    )
    if not result.is_error:
        stream.push("showcase-06", "tool", "file_editor: create report")
        print(f"  ✅ Created {report_path.name}")


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 6: STATE MANAGER — Persistent Storage & Tracking
# ═════════════════════════════════════════════════════════════════════════════
# This section demonstrates persistent data storage:
# - Project creation and management
# - Task creation, tracking, and status updates
# - Message storage for conversation history
# - Sub-sessions for parallel work streams
# - Database queries and filtering
# ═════════════════════════════════════════════════════════════════════════════

async def showcase_state_manager(state_mgr: StateManager) -> None:
    """
    Demonstrate StateManager for persistent task/message storage.
    
    This function shows:
    1. Creating and storing projects
    2. Creating and tracking tasks with status
    3. Retrieving data from persistent storage
    4. Working with associations (tasks belong to projects)
    
    StateManager uses SQLite for:
    - Durability across agent restarts
    - Complex queries and filtering
    - Transaction support for consistency
    
    Args:
        state_mgr: StateManager instance with SQLite backend
    """
    print("\n" + "=" * 80)
    print("SECTION 6: StateManager — Persistent Storage")
    print("=" * 80)

    # ────────────────────────────────────────────────────────────────────────
    # 6.1: Create a project
    # ────────────────────────────────────────────────────────────────────────
    # Projects organize related tasks and provide a namespace for data
    # Includes metadata like name, description, and tags
    print("\n[6.1] Creating a project …")
    project = Project(
        name="Showcase Project",
        description="Demonstrating weebot capabilities",
        tags=["demo", "comprehensive"]
    )
    state_mgr.save_project(project)
    print(f"  ✅ Project created: {project.id}")

    # ────────────────────────────────────────────────────────────────────────
    # 6.2: Create tasks
    # ────────────────────────────────────────────────────────────────────────
    # Tasks represent individual work items with status tracking
    # Status can be: pending, in_progress, completed, failed
    # Linked to parent project via project_id
    print("\n[6.2] Creating tasks …")
    tasks = [
        Task(project_id=project.id, title="System analysis", status="completed"),
        Task(project_id=project.id, title="Data processing", status="completed"),
        Task(project_id=project.id, title="Report generation", status="in_progress"),
    ]
    for task in tasks:
        state_mgr.save_task(task)
    print(f"  ✅ Created {len(tasks)} tasks")

    # ────────────────────────────────────────────────────────────────────────
    # 6.3: Retrieve from storage
    # ────────────────────────────────────────────────────────────────────────
    # Demonstrates retrieval and filtering of stored data
    # Shows relational queries (tasks by project_id)
    print("\n[6.3] Retrieving stored data …")
    retrieved = state_mgr.get_project(project.id)
    if retrieved:
        print(f"  ✅ Retrieved project: {retrieved.name}")
        stored_tasks = state_mgr.get_tasks(project_id=project.id)
        print(f"  ✅ Found {len(stored_tasks)} associated tasks")
        for task in stored_tasks:
            print(f"     - {task.title} ({task.status})")


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 7: ACTIVITY STREAM — Event Tracking & Monitoring
# ═════════════════════════════════════════════════════════════════════════════
# This section demonstrates event tracking and monitoring:
# - Real-time activity logging
# - Event categorization (tool, decision, error, milestone)
# - Event history with timestamps
# - Activity stream analysis and reporting
# ═════════════════════════════════════════════════════════════════════════════

async def showcase_activity_stream(stream: ActivityStream) -> None:
    """
    Demonstrate ActivityStream for real-time event tracking.
    
    This function shows:
    1. Reviewing logged events from previous steps
    2. Adding custom milestone and summary events
    3. Event retrieval and iteration
    
    ActivityStream features:
    - Ring buffer (deque) with max 200 events
    - Automatic timestamp on each event
    - Event kinds: tool, decision, error, milestone, system, summary
    - Useful for debugging and monitoring agent behavior
    
    Args:
        stream: ActivityStream instance (shared across all sections)
    """
    print("\n" + "=" * 80)
    print("SECTION 7: ActivityStream — Event Tracking")
    print("=" * 80)

    # ────────────────────────────────────────────────────────────────────────
    # 7.1: Display logged events
    # ────────────────────────────────────────────────────────────────────────
    # Shows all events from the activity stream collected during execution
    # Demonstrates real-time monitoring of agent activity
    print(f"\n[7.1] Logged events so far: {len(stream.recent())} events")
    print("      Recent activity:")
    for event in stream.recent()[-10:]:
        timestamp = event.timestamp.strftime("%H:%M:%S")
        print(f"        [{timestamp}] {event.kind:12} | {event.message}")

    # ────────────────────────────────────────────────────────────────────────
    # 7.2: Add custom events
    # ────────────────────────────────────────────────────────────────────────
    # Shows how to manually push events to the stream
    # Useful for marking milestones and summarizing execution
    print(f"\n[7.2] Adding custom events …")
    stream.push("showcase-06", "milestone", "Showcase execution completed")
    stream.push("showcase-06", "summary", f"Total {len(stream.recent())} events logged")
    print(f"  ✅ Activity stream now contains {len(stream.recent())} events")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATION
# ═════════════════════════════════════════════════════════════════════════════
# This is the main entry point that orchestrates all showcase sections.
# It demonstrates proper async patterns and error handling.
# ═════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    """
    Run comprehensive showcase of all weebot capabilities.
    
    This function orchestrates the complete showcase by:
    1. Initializing core components (settings, stream, state manager)
    2. Running all showcase sections sequentially
    3. Displaying comprehensive summary and statistics
    4. Providing guidance for next steps
    
    Error handling:
    - Catches and reports any exceptions
    - Prints full traceback for debugging
    - Continues to summary even if errors occur
    """
    print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                   WEEBOT COMPREHENSIVE CAPABILITIES SHOWCASE                ║
║                     All Features in Production Scenarios                    ║
║              Author: Georgios-Chrysovalantis Chatzivantsidis               ║
╚══════════════════════════════════════════════════════════════════════════════╝
Started: {datetime.now().isoformat()}
""")

    try:
        # ────────────────────────────────────────────────────────────────────
        # Initialize core components
        # ────────────────────────────────────────────────────────────────────
        stream, state_mgr = await showcase_initialization()

        # ────────────────────────────────────────────────────────────────────
        # Run all showcase sections
        # ────────────────────────────────────────────────────────────────────
        # Each section builds on previous ones and uses the shared
        # stream and state_mgr instances
        await showcase_bash_tool(stream)
        await showcase_python_tool(stream)
        await showcase_web_search(stream)
        await showcase_file_editor(stream)
        await showcase_state_manager(state_mgr)
        await showcase_activity_stream(stream)

        # ────────────────────────────────────────────────────────────────────
        # Summary and next steps
        # ────────────────────────────────────────────────────────────────────
        print("\n" + "=" * 80)
        print("SUMMARY — All Sections Complete")
        print("=" * 80)
        print(f"\n✅ Showcase execution finished successfully!")
        print(f"\n📊 Statistics:")
        print(f"   - Events tracked: {len(stream.recent())}")
        print(f"   - Tools executed: 5+ (bash, python, web, file, state)")
        print(f"   - Output directory: {Path(__file__).parent / 'output'}")
        print(f"\n📄 Generated files:")
        output_dir = Path(__file__).parent / "output"
        for f in output_dir.glob("showcase_*"):
            print(f"   - {f.name}")
        print(f"\n🚀 Next steps:")
        print(f"   - Review generated files in examples/output/")
        print(f"   - Customize showcase_config.yaml for your needs")
        print(f"   - Explore individual tool examples (01-05)")
        print(f"   - Deploy weebot agent for production tasks")

    except Exception as e:
        print(f"\n❌ Error during showcase: {e}")
        import traceback
        traceback.print_exc()


# ═════════════════════════════════════════════════════════════════════════════
# SCRIPT ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Run the async main function using asyncio.run()
    # This is the recommended way to run async code from sync context
    asyncio.run(main())
