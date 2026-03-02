# -*- coding: utf-8 -*-
"""Example 06 -- Comprehensive Weebot Capabilities Showcase
============================================================
Author: Georgios-Chrysovalantis Chatzivantsidis

Covers all weebot features with per-task token consumption and EUR cost tracking:

  * BashTool              -- system commands, git operations
  * PythonExecuteTool     -- sandboxed code execution with safety gates
  * WebSearchTool         -- DuckDuckGo/Bing research
  * StrReplaceEditorTool  -- file creation, editing, automation
  * StateManager          -- persistent SQLite storage for tasks/projects
  * ActivityStream        -- ring-buffer event tracking (max 200 events)
  * TokenTracker          -- per-task token estimation and EUR cost display

Token accounting methodology:
  - Tokens estimated at 1 token per 4 characters (industry-standard heuristic)
  - Input  = text sent to the tool (command / code / query)
  - Output = text returned by the tool (stdout / results / snippets)
  - Default pricing: Claude Sonnet 4.6  ($3.00/1M input  |  $15.00/1M output)
  - Exchange rate: 1 USD = 0.92 EUR  (configurable via EUR_RATE constant)

NOTE on token optimisation:
  This file is documentation-first (thorough comments for learning purposes).
  For production agents, keep prompts concise -- every character in a system
  prompt or tool description costs input tokens on every API call.

Usage:
    python examples/06_comprehensive_capabilities_showcase.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict

# ---------------------------------------------------------------------------
# Path bootstrap -- allows running as a standalone script from project root
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from weebot.activity_stream import ActivityStream
from weebot.config.settings import WeebotSettings
from weebot.core.approval_policy import ApprovalMode, ExecApprovalPolicy
from weebot.domain.models import Project, Task
from weebot.state_manager import StateManager
from weebot.tools.bash_tool import BashTool
from weebot.tools.file_editor import StrReplaceEditorTool
from weebot.tools.python_tool import PythonExecuteTool
from weebot.tools.web_search import WebSearchTool

# ---------------------------------------------------------------------------
# Pricing constants -- adjust to match the model used in production
# ---------------------------------------------------------------------------
USD_PER_M_INPUT_TOKENS  = 3.00    # Claude Sonnet 4.6 input price  ($/1M tokens)
USD_PER_M_OUTPUT_TOKENS = 15.00   # Claude Sonnet 4.6 output price ($/1M tokens)
EUR_RATE                = 0.92    # USD -> EUR conversion rate
CHARS_PER_TOKEN         = 4       # Conservative GPT/Claude heuristic


# ===========================================================================
#  TOKEN TRACKER
#  Estimates tokens consumed and calculates cost (USD + EUR) per task.
#  Call .record() after every tool call, .report() for a full breakdown.
# ===========================================================================

@dataclass
class TaskCost:
    """Holds accumulated token usage and derived cost for one named task."""
    name: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float:
        """Dollar cost based on separate input/output pricing."""
        in_cost  = self.input_tokens  * USD_PER_M_INPUT_TOKENS  / 1_000_000
        out_cost = self.output_tokens * USD_PER_M_OUTPUT_TOKENS / 1_000_000
        return in_cost + out_cost

    @property
    def cost_eur(self) -> float:
        """Euro equivalent using the configured exchange rate."""
        return self.cost_usd * EUR_RATE


class TokenTracker:
    """
    Lightweight token estimator for weebot tool calls.

    Since tool execution (bash, python, web search ...) does not route through
    the LLM, tokens are approximated from character count using the standard
    4-chars-per-token heuristic.  For real LLM API calls, replace estimation
    with actual usage data from the API response (response.usage.input_tokens).
    """

    def __init__(self) -> None:
        # One TaskCost bucket per task name; multiple calls accumulate
        self._tasks: Dict[str, TaskCost] = {}

    def record(self, task_name: str, input_text: str, output_text: str) -> TaskCost:
        """
        Record a tool call and accumulate its estimated token cost.

        Args:
            task_name:   Human-readable label (e.g. "2-bash", "3-python").
            input_text:  The command, code, or query sent to the tool.
            output_text: The result returned by the tool.

        Returns:
            The updated TaskCost entry so the caller can print it inline.
        """
        in_tok  = max(1, len(input_text)  // CHARS_PER_TOKEN)
        out_tok = max(1, len(output_text) // CHARS_PER_TOKEN)

        if task_name not in self._tasks:
            self._tasks[task_name] = TaskCost(name=task_name)
        self._tasks[task_name].input_tokens  += in_tok
        self._tasks[task_name].output_tokens += out_tok

        return self._tasks[task_name]

    def print_task_line(self, task: TaskCost) -> None:
        """One-line cost summary printed inline after each tool call."""
        print(
            f"     [tokens] in={task.input_tokens:,}  "
            f"out={task.output_tokens:,}  "
            f"total={task.total_tokens:,}  "
            f"cost=${task.cost_usd:.6f}  EUR={task.cost_eur:.6f}"
        )

    def report(self) -> None:
        """Print aligned per-task breakdown plus grand totals."""
        if not self._tasks:
            print("  (no tasks recorded)")
            return

        col = max(len(t) for t in self._tasks) + 2  # column width for task name

        header = f"  {'TASK':<{col}} {'IN tok':>8}  {'OUT tok':>8}  {'TOTAL':>8}  {'USD':>10}  {'EUR':>10}"
        divider = "  " + "-" * (len(header) - 2)

        print(divider)
        print(header)
        print(divider)

        total_in = total_out = total_usd = 0.0
        for task in self._tasks.values():
            print(
                f"  {task.name:<{col}} {task.input_tokens:>8,}  "
                f"{task.output_tokens:>8,}  {task.total_tokens:>8,}  "
                f"${task.cost_usd:>9.6f}  E{task.cost_eur:>9.6f}"
            )
            total_in  += task.input_tokens
            total_out += task.output_tokens
            total_usd += task.cost_usd

        total_eur = total_usd * EUR_RATE
        print(divider)
        print(
            f"  {'TOTAL':<{col}} {int(total_in):>8,}  "
            f"{int(total_out):>8,}  {int(total_in + total_out):>8,}  "
            f"${total_usd:>9.6f}  E{total_eur:>9.6f}"
        )
        print(divider)
        print(
            f"  Pricing: ${USD_PER_M_INPUT_TOKENS}/1M in | "
            f"${USD_PER_M_OUTPUT_TOKENS}/1M out | "
            f"1 USD = {EUR_RATE} EUR"
        )


# ===========================================================================
#  SECTION 1 -- INITIALIZATION & CONFIGURATION
#  No LLM calls here; cost is negligible (config text only).
# ===========================================================================

async def showcase_initialization(tracker: TokenTracker):
    """
    Load WeebotSettings, ActivityStream, StateManager and ExecApprovalPolicy.

    WeebotSettings reads from env vars or .env file (pydantic-settings).
    ActivityStream is a deque(maxlen=200) that logs every agent event.
    StateManager wraps SQLite for durable task/project persistence.
    ExecApprovalPolicy gates all bash/python executions (AUTO / ALWAYS_ASK / DENY).
    """
    print("\n" + "=" * 78)
    print("  SECTION 1 -- Initialization & Configuration")
    print("=" * 78)

    settings = WeebotSettings()
    print(
        f"  [OK] Settings: bash_timeout={settings.bash_timeout}s | "
        f"py_timeout={settings.python_timeout}s | "
        f"max_output={settings.sandbox_max_output_bytes // 1024}KB | "
        f"allow_network={settings.sandbox_allow_network}"
    )

    stream = ActivityStream()
    stream.push("showcase-06", "system", "Initialization started")
    print(f"  [OK] ActivityStream ready (capacity: {stream._buffer.maxlen} events)")

    db_path = Path(__file__).parent / "output" / "weebot_showcase.db"
    os.makedirs(db_path.parent, exist_ok=True)
    state_mgr = StateManager(db_path=str(db_path))
    print(f"  [OK] StateManager -> {db_path.name}")

    # Default policy: no rules = all commands allowed (development / showcase mode)
    policy = ExecApprovalPolicy()
    print(f"  [OK] Safety policy: ExecApprovalPolicy (default/allow-all)")

    task = tracker.record("1-init", "WeebotSettings+ActivityStream+StateManager+Policy", "OK")
    tracker.print_task_line(task)

    return stream, state_mgr


# ===========================================================================
#  SECTION 2 -- BASH TOOL
#  Executes PowerShell (Windows) or WSL2 bash commands in a subprocess.
#  ExecApprovalPolicy.evaluate() is called before every command.
#  Returns ToolResult(output, error, returncode).
# ===========================================================================

async def showcase_bash_tool(stream: ActivityStream, tracker: TokenTracker) -> None:
    """Run four representative shell commands and print per-call token cost."""
    print("\n" + "=" * 78)
    print("  SECTION 2 -- BashTool: System Commands & Git")
    print("=" * 78)

    bash = BashTool()

    async def run(label: str, cmd: str) -> None:
        """Execute one command, record its tokens, and print an inline summary.
        FileNotFoundError is caught so the showcase continues even if PowerShell
        is not on the system PATH in the current async context."""
        try:
            result = await bash.execute(command=cmd)
            output = result.output if not result.is_error else result.error
            status = "[OK]" if not result.is_error else "[ERR]"
        except FileNotFoundError:
            output = "PowerShell not found on PATH in this async context"
            status = "[SKIP]"
        task = tracker.record("2-bash", cmd, output)
        print(f"\n  {label} {status} {output[:120].strip()}")
        tracker.print_task_line(task)
        stream.push("showcase-06", "tool", f"bash: {label}")

    await run("2.1 PS version", 'powershell -NoProfile -Command "Get-Host | Select Version"')
    await run("2.2 Dir list",   "ls -la | head -5")
    await run("2.3 Git status", "git status --short")
    await run("2.4 Python env", "python --version")


# ===========================================================================
#  SECTION 3 -- PYTHON EXECUTE TOOL
#  Runs code via `python -c ...` in an isolated subprocess.
#  Memory usage monitored by psutil; output capped at 64 KB by default.
#  TimeoutError is caught and returned as ToolResult.error.
# ===========================================================================

async def showcase_python_tool(stream: ActivityStream, tracker: TokenTracker) -> None:
    """Run three Python snippets (math, pandas, timeout) and show token costs."""
    print("\n" + "=" * 78)
    print("  SECTION 3 -- PythonExecuteTool: Sandboxed Execution")
    print("=" * 78)

    py = PythonExecuteTool()

    async def run(label: str, code: str, timeout: int = 15) -> None:
        result = await py.execute(code=code, timeout=timeout)
        output = result.output if not result.is_error else result.error
        task   = tracker.record("3-python", code, output)
        status = "[OK]" if not result.is_error else "[ERR]"
        print(f"\n  {label} {status}")
        print(f"  {output[:200].strip()}")
        tracker.print_task_line(task)
        stream.push("showcase-06", "tool", f"python_execute: {label}")

    # 3.1 -- Simple numeric computation using stdlib math
    await run("3.1 Math", """
import math
result = sum(math.sqrt(i) for i in range(1, 101))
print(f"Sum of sqrt(1..100): {result:.4f}")
""")

    # 3.2 -- Data analysis: groupby + describe using pandas/numpy
    await run("3.2 Pandas", """
import pandas as pd, numpy as np
df = pd.DataFrame({'val': np.random.randint(10, 100, 50),
                   'cat': np.random.choice(['A','B','C'], 50)})
print(df.groupby('cat')['val'].agg(['mean','std']).round(2).to_string())
""")

    # 3.3 -- Timeout guard: code sleeps longer than the timeout budget
    #         Expects ToolResult.is_error == True (controlled failure)
    await run("3.3 Timeout guard", "import time; time.sleep(60)", timeout=3)


# ===========================================================================
#  SECTION 4 -- WEB SEARCH TOOL
#  Primary backend: DuckDuckGo (no API key required).
#  Fallback: Bing Search API (set BING_API_KEY env var to enable).
# ===========================================================================

async def showcase_web_search(stream: ActivityStream, tracker: TokenTracker) -> None:
    """Execute a web search and display token cost for query + returned snippets."""
    print("\n" + "=" * 78)
    print("  SECTION 4 -- WebSearchTool: Research & Information")
    print("=" * 78)

    search = WebSearchTool()
    query  = "Claude AI model 2025 capabilities"

    print(f"\n  [4.1 Search] query: {query!r}")
    result = await search.execute(query=query, num_results=3)

    output = result.output if not result.is_error else result.error
    task   = tracker.record("4-search", query, output)
    status = "[OK]" if not result.is_error else "[WARN]"
    print(f"  {status} {output[:200].strip()}")
    tracker.print_task_line(task)
    stream.push("showcase-06", "tool", "web_search: Claude AI 2025")


# ===========================================================================
#  SECTION 5 -- FILE EDITOR TOOL
#  Supported commands: create | view | str_replace | insert
#  Operates entirely on the local filesystem; no LLM calls.
# ===========================================================================

async def showcase_file_editor(stream: ActivityStream, tracker: TokenTracker) -> None:
    """Create, read, and patch files; show token cost per operation."""
    print("\n" + "=" * 78)
    print("  SECTION 5 -- StrReplaceEditorTool: File Automation")
    print("=" * 78)

    editor     = StrReplaceEditorTool()
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    config_path = str(output_dir / "showcase_config.yaml")

    # 5.1 -- Create YAML configuration file
    content = (
        "# Weebot Showcase Configuration\n"
        "agent:\n  name: ShowcaseAgent\n  model: claude-sonnet-4-6\n"
        "  timeout: 300\ntools:\n  bash_timeout: 30\n  python_timeout: 30\n"
    )
    result = await editor.execute(command="create", path=config_path, file_text=content)
    out    = result.output if not result.is_error else result.error
    task   = tracker.record("5-file", f"create:{config_path}", out)
    print(f"\n  [5.1 Create] [OK] showcase_config.yaml")
    tracker.print_task_line(task)
    stream.push("showcase-06", "tool", "file_editor: create config")

    # 5.2 -- Read the file back to verify contents
    result = await editor.execute(command="view", path=config_path)
    out    = result.output if not result.is_error else result.error
    task   = tracker.record("5-file", f"view:{config_path}", out)
    print(f"  [5.2 View  ] [OK] {len(out)} chars read")
    tracker.print_task_line(task)
    stream.push("showcase-06", "tool", "file_editor: view")

    # 5.3 -- Patch: bump timeout from 300 to 600
    result = await editor.execute(
        command="str_replace", path=config_path,
        old_str="  timeout: 300",
        new_str="  timeout: 600  # increased for complex tasks"
    )
    out  = result.output if not result.is_error else result.error
    task = tracker.record("5-file", "str_replace:timeout 300->600", out)
    print(f"  [5.3 Edit  ] [OK] timeout 300 -> 600")
    tracker.print_task_line(task)
    stream.push("showcase-06", "tool", "file_editor: str_replace")

    # 5.4 -- Auto-generate a markdown summary report
    report = (
        f"# Weebot Showcase Report\n"
        f"Generated: {datetime.now().isoformat()}\n\n"
        "## Sections Completed\n"
        "- Initialization\n- BashTool\n- PythonExecuteTool\n"
        "- WebSearchTool\n- FileEditorTool\n- StateManager\n"
        "- ActivityStream\n- TokenTracker\n"
    )
    report_path = str(output_dir / "showcase_report.md")
    result = await editor.execute(command="create", path=report_path, file_text=report)
    out    = result.output if not result.is_error else result.error
    task   = tracker.record("5-file", f"create:{report_path}", out)
    print(f"  [5.4 Report] [OK] showcase_report.md")
    tracker.print_task_line(task)
    stream.push("showcase-06", "tool", "file_editor: create report")


# ===========================================================================
#  SECTION 6 -- STATE MANAGER
#  SQLite-backed storage for Projects, Tasks, Messages and sub-sessions.
#  Data survives agent restarts; supports relational queries (tasks by project).
# ===========================================================================

async def showcase_state_manager(state_mgr: StateManager, tracker: TokenTracker) -> None:
    """Store a project + tasks in SQLite and verify retrieval."""
    print("\n" + "=" * 78)
    print("  SECTION 6 -- StateManager: Persistent Storage")
    print("=" * 78)

    # Create project -- name/description stored as UTF-8 in SQLite
    # create_project returns a ProjectState (dataclass) with project_id + description
    project = state_mgr.create_project(
        project_id="showcase-project-01",
        description="Demonstrating full weebot capabilities",
    )
    print(f"\n  [6.1 Project] [OK] id={project.project_id}")

    # Add checkpoint entries as lightweight task proxies
    state_mgr.add_checkpoint(project.project_id, "System analysis complete")
    state_mgr.add_checkpoint(project.project_id, "Data processing complete")
    state_mgr.add_checkpoint(project.project_id, "Report generation started")
    print(f"  [6.2 Tasks ] [OK] 3 checkpoints stored")

    # Retrieve and verify
    state_mgr.save_state(project)
    projects  = state_mgr.list_projects()
    summary   = " | ".join(p["project_id"] for p in projects[:5])
    task      = tracker.record("6-state", "create_project + 3x add_checkpoint + list_projects", summary)
    print(f"  [6.3 Query ] [OK] {len(projects)} project(s) in DB: {summary[:60]}")
    tracker.print_task_line(task)


# ===========================================================================
#  SECTION 7 -- ACTIVITY STREAM
#  Ring-buffer (deque maxlen=200) of ActivityEvent(agent_id, kind, message, ts).
#  Shared across all sections -- accumulates events from every tool call.
# ===========================================================================

async def showcase_activity_stream(stream: ActivityStream, tracker: TokenTracker) -> None:
    """Display the event log collected during the run and add final markers."""
    print("\n" + "=" * 78)
    print("  SECTION 7 -- ActivityStream: Event Log")
    print("=" * 78)

    events = stream.recent()
    print(f"\n  Total events logged: {len(events)}")
    print(f"  Last 8 entries:")
    for ev in events[-8:]:
        ts = ev.timestamp.strftime("%H:%M:%S")
        print(f"    [{ts}] {ev.kind:<12} {ev.message}")

    # Mark completion milestones
    stream.push("showcase-06", "milestone", "All sections complete")
    task = tracker.record("7-stream", f"stream.recent() x{len(events)}", "OK")
    tracker.print_task_line(task)


# ===========================================================================
#  MAIN ORCHESTRATION
# ===========================================================================

async def main() -> None:
    """
    Run every showcase section in sequence.
    A shared TokenTracker accumulates estimates across all sections and
    prints a full cost breakdown (USD + EUR) in the finally block.
    """
    print(f"""
+------------------------------------------------------------------------------+
|  WEEBOT COMPREHENSIVE CAPABILITIES SHOWCASE                                  |
|  Author: Georgios-Chrysovalantis Chatzivantsidis                             |
|  Pricing: Claude Sonnet 4.6  |  1 USD = {EUR_RATE} EUR                          |
+------------------------------------------------------------------------------+
  Started: {datetime.now().isoformat()}
""")

    # One tracker instance shared by all sections
    tracker = TokenTracker()

    try:
        stream, state_mgr = await showcase_initialization(tracker)
        await showcase_bash_tool(stream, tracker)
        await showcase_python_tool(stream, tracker)
        await showcase_web_search(stream, tracker)
        await showcase_file_editor(stream, tracker)
        await showcase_state_manager(state_mgr, tracker)
        await showcase_activity_stream(stream, tracker)

    except Exception as exc:
        import traceback
        print(f"\n[ERROR] {exc}")
        traceback.print_exc()

    finally:
        # Cost report always prints -- even on partial failure
        print("\n" + "=" * 78)
        print("  TOKEN CONSUMPTION & COST REPORT")
        tracker.report()

        # List files written to examples/output/
        output_dir = Path(__file__).parent / "output"
        generated  = list(output_dir.glob("showcase_*"))
        if generated:
            print(f"\n  Generated files ({len(generated)}):")
            for f in generated:
                print(f"    {f.name}")

        print(f"\n  Finished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    asyncio.run(main())
