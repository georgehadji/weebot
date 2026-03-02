# Weebot Comprehensive Capabilities Guide

**Author**: Georgios-Chrysovalantis Chatzivantsidis

A complete reference for all weebot features, with practical examples and use cases.

**Σύντομη Περιγραφή**: Αυτός ο οδηγός καλύπτει όλες τις δυνατότητες του weebot framework — από βασικές εντολές συστήματος μέχρι σύνθετη αυτοματοποίηση και ενσωμάτωση MCP.

---

## Table of Contents

1. [Initialization & Configuration](#initialization--configuration)
2. [BashTool — System Commands](#bashtool--system-commands)
3. [PythonExecuteTool — Sandboxed Execution](#pythonexecutetool--sandboxed-execution)
4. [WebSearchTool — Research](#websearchtool--research)
5. [StrReplaceEditorTool — File Operations](#streplaceeditortool--file-operations)
6. [AdvancedBrowserTool — Browser Automation](#advancedbrowsertool--browser-automation)
7. [SchedulerTool — Job Scheduling](#schedulertool--job-scheduling)
8. [StateManager — Persistent Storage](#statemanager--persistent-storage)
9. [ActivityStream — Event Tracking](#activitystream--event-tracking)
10. [Safety & Approval Policies](#safety--approval-policies)
11. [MCP Server Integration](#mcp-server-integration)
12. [Production Workflows](#production-workflows)

---

## Initialization & Configuration

### Loading Settings

```python
from weebot.config.settings import WeebotSettings

settings = WeebotSettings()
print(settings.bash_timeout)        # 30 seconds
print(settings.python_timeout)      # 30 seconds
print(settings.sandbox_max_output_bytes)  # 65536 (64 KB)
```

### Customization via .env

Create a `.env` file in your project:

```env
LOG_LEVEL=INFO
BASH_TIMEOUT=60
PYTHON_TIMEOUT=60
SANDBOX_MAX_OUTPUT_BYTES=131072
MODEL_PROVIDER=anthropic
```

### ActivityStream for Event Tracking

```python
from weebot.activity_stream import ActivityStream

stream = ActivityStream(maxlen=200)  # Ring buffer
stream.push(agent_id="my-agent", kind="tool", message="Started task")

for event in stream.recent():
    print(f"[{event.timestamp}] {event.kind}: {event.message}")
```

---

## BashTool — System Commands

Execute PowerShell, WSL2 bash, or system commands.

### Basic Usage

```python
from weebot.tools.bash_tool import BashTool

bash = BashTool()

# Simple command
result = await bash.execute(command="ls -la")
print(result.output)
print(result.error)
print(result.returncode)  # 0 = success

# With timeout
result = await bash.execute(
    command="long-running-task",
    timeout=120
)

# With working directory
result = await bash.execute(
    command="npm install",
    working_dir="/path/to/project"
)
```

### Common Scenarios

**1. Git Operations**
```python
# Check status
result = await bash.execute("git status --short")

# Get recent commits
result = await bash.execute("git log --oneline -10")

# Clone repository
result = await bash.execute("git clone https://github.com/user/repo.git")
```

**2. System Information**
```python
# PowerShell: system info
result = await bash.execute(
    'powershell -NoProfile -Command "Get-ComputerInfo | Select CsSystemType"'
)

# Disk usage
result = await bash.execute("df -h")

# Process list
result = await bash.execute("ps aux | grep python")
```

**3. Package Management**
```python
# Check Python version
result = await bash.execute("python --version")

# Install packages
result = await bash.execute("pip install pandas numpy")

# List installed packages
result = await bash.execute("pip list | grep -i torch")
```

### Safety & Error Handling

```python
result = await bash.execute("rm -rf /important/data")

if result.is_error:
    print(f"Command failed: {result.error}")
    print(f"Exit code: {result.returncode}")
else:
    print("Success!")
```

---

## PythonExecuteTool — Sandboxed Execution

Run Python code in isolated subprocess with memory limits and timeouts.

### Basic Usage

```python
from weebot.tools.python_tool import PythonExecuteTool

python = PythonExecuteTool()

code = """
import math
result = sum([math.sqrt(i) for i in range(100)])
print(f"Result: {result}")
"""

result = await python.execute(code=code, timeout=30)
print(result.output)
```

### Data Science & Analysis

```python
code = """
import pandas as pd
import numpy as np

# Create dataset
data = {
    'date': pd.date_range('2026-01-01', periods=100),
    'value': np.random.normal(100, 15, 100),
    'category': np.random.choice(['A', 'B', 'C'], 100)
}
df = pd.DataFrame(data)

# Analysis
print("Dataset shape:", df.shape)
print("\\nValue statistics:")
print(df['value'].describe())
print("\\nBy category:")
print(df.groupby('category')['value'].agg(['mean', 'std']))
"""

result = await python.execute(code=code, timeout=30)
print(result.output)
```

### Machine Learning Workflow

```python
code = """
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score

# Load data
iris = load_iris()
X_train, X_test, y_train, y_test = train_test_split(
    iris.data, iris.target, test_size=0.2, random_state=42
)

# Train model
model = RandomForestClassifier(n_estimators=10)
model.fit(X_train, y_train)

# Evaluate
predictions = model.predict(X_test)
accuracy = accuracy_score(y_test, predictions)
print(f"Model Accuracy: {accuracy:.2%}")
print(f"Feature Importances: {dict(enumerate(model.feature_importances_))}")
"""

result = await python.execute(code=code, timeout=30)
print(result.output)
```

### Timeout & Resource Protection

```python
# Code that takes too long
code = "import time; time.sleep(100)"

result = await python.execute(code=code, timeout=5)
if result.is_error:
    print(f"Timeout: {result.error}")  # "Timed out after 5.0s"
```

---

## WebSearchTool — Research

Search DuckDuckGo or Bing for information.

### Basic Search

```python
from weebot.tools.web_search import WebSearchTool

search = WebSearchTool()

result = await search.execute(
    query="Claude AI model latest features",
    num_results=5
)

print(result.output)  # Formatted search results
```

### Research Workflow

```python
# Multi-query research
queries = [
    "Model Context Protocol MCP 2025",
    "Claude 4.6 capabilities",
    "AI agent frameworks comparison"
]

for query in queries:
    result = await search.execute(query=query, num_results=3)
    if not result.is_error:
        print(f"\n=== {query} ===")
        print(result.output[:500])
```

### Competitive Intelligence

```python
companies = ["OpenAI", "Anthropic", "Google DeepMind"]

for company in companies:
    result = await search.execute(
        query=f"{company} recent announcements 2025",
        num_results=5
    )
    print(f"\n{company}:")
    print(result.output[:300])
```

---

## StrReplaceEditorTool — File Operations

Create, read, edit, and manage files.

### Create Files

```python
from weebot.tools.file_editor import StrReplaceEditorTool

editor = StrReplaceEditorTool()

# Create new file
result = await editor.execute(
    command="create",
    path="/path/to/config.yaml",
    file_text="""
app:
  name: MyApp
  version: 1.0
  debug: false
"""
)
```

### View Files

```python
# Read existing file
result = await editor.execute(
    command="view",
    path="/path/to/config.yaml"
)
print(result.output)
```

### Edit Files

```python
# Find and replace
result = await editor.execute(
    command="str_replace",
    path="/path/to/config.yaml",
    old_str="  debug: false",
    new_str="  debug: true"
)
```

### Generate Reports

```python
report = f"""
# Project Report
Generated: {datetime.now().isoformat()}

## Summary
- Tasks completed: 10
- Errors: 0
- Performance: 98%

## Details
- System uptime: 24h
- Memory usage: 2.4 GB
- CPU usage: 15%
"""

result = await editor.execute(
    command="create",
    path="/output/report.md",
    file_text=report
)
```

---

## AdvancedBrowserTool — Browser Automation

Automate web interactions with Playwright.

### Navigation & Page Inspection

```python
from weebot.tools.advanced_browser import AdvancedBrowserTool

browser = AdvancedBrowserTool()

# Navigate to URL
result = await browser.execute(
    action="navigate",
    url="https://example.com"
)

# Take screenshot
result = await browser.execute(
    action="screenshot"
)

# Get page title
result = await browser.execute(
    action="execute_script",
    script="return document.title"
)
print(result.output)
```

### Form Filling & Submission

```python
# Fill login form
result = await browser.execute(
    action="fill",
    selector='input[name="username"]',
    value="user@example.com"
)

result = await browser.execute(
    action="fill",
    selector='input[name="password"]',
    value="secret123"
)

# Click submit
result = await browser.execute(
    action="click",
    selector='button[type="submit"]'
)

# Wait for navigation
result = await browser.execute(
    action="wait_for_navigation",
    timeout=10000
)
```

### Web Scraping

```python
# Extract data
script = """
const items = document.querySelectorAll('.product');
return Array.from(items).map(item => ({
    title: item.querySelector('.title').innerText,
    price: item.querySelector('.price').innerText
}));
"""

result = await browser.execute(
    action="execute_script",
    script=script
)
print(result.output)  # JSON array
```

---

## SchedulerTool — Job Scheduling

Schedule recurring tasks with APScheduler.

### Interval Jobs

```python
from weebot.tools.scheduler import SchedulerTool

scheduler = SchedulerTool()

# Run task every 1 hour
result = await scheduler.execute(
    action="add_job",
    job_id="data-sync",
    job_type="interval",
    minutes=60,
    func_name="sync_data",
    func_args={"source": "database"}
)
```

### Cron Jobs

```python
# Run daily at 2 AM
result = await scheduler.execute(
    action="add_job",
    job_id="nightly-backup",
    job_type="cron",
    hour=2,
    minute=0,
    func_name="backup_database"
)

# Run every Monday at 9 AM
result = await scheduler.execute(
    action="add_job",
    job_id="weekly-report",
    job_type="cron",
    day_of_week="mon",
    hour=9,
    func_name="generate_report"
)
```

### Job Management

```python
# List all jobs
result = await scheduler.execute(action="list_jobs")
print(result.output)

# Pause job
result = await scheduler.execute(
    action="pause_job",
    job_id="data-sync"
)

# Resume job
result = await scheduler.execute(
    action="resume_job",
    job_id="data-sync"
)

# Remove job
result = await scheduler.execute(
    action="remove_job",
    job_id="data-sync"
)
```

---

## StateManager — Persistent Storage

Store and retrieve tasks, projects, and messages.

### Projects & Tasks

```python
from weebot.state_manager import StateManager
from weebot.domain.models import Project, Task

state = StateManager(db_path="weebot.db")

# Create project
project = Project(
    name="Data Pipeline",
    description="ETL automation",
    tags=["production"]
)
state.save_project(project)

# Create tasks
task1 = Task(
    project_id=project.id,
    title="Extract data",
    status="pending"
)
task2 = Task(
    project_id=project.id,
    title="Transform data",
    status="pending"
)

state.save_task(task1)
state.save_task(task2)

# Retrieve data
project = state.get_project(project.id)
tasks = state.get_tasks(project_id=project.id, status="pending")

for task in tasks:
    print(f"- {task.title} ({task.status})")
```

### Messages & Conversation History

```python
from weebot.domain.models import Message

# Save message
message = Message(
    agent_id="my-agent",
    role="assistant",
    content="Analysis complete"
)
state.save_message(message)

# Retrieve conversation
messages = state.get_messages(agent_id="my-agent")
for msg in messages:
    print(f"{msg.role}: {msg.content}")
```

### Sub-sessions

```python
# Create subsession for parallel work
subsession = state.create_subsession(
    parent_agent_id="main-agent",
    name="Analysis Branch"
)

# Work within subsession
task = Task(
    project_id=project.id,
    title="Sub-analysis"
)
state.save_task(task, subsession_id=subsession.id)

# Retrieve subsession data
subsession_data = state.get_subsession(subsession.id)
```

---

## ActivityStream — Event Tracking

Track and monitor agent activities in real time.

### Event Types

```python
from weebot.activity_stream import ActivityStream

stream = ActivityStream()

# Tool execution
stream.push("agent-id", "tool", "web_search: AI models")

# Decision point
stream.push("agent-id", "decision", "Choosing between 3 strategies")

# Error
stream.push("agent-id", "error", "Network timeout")

# Milestone
stream.push("agent-id", "milestone", "Phase 1 completed")
```

### Querying Events

```python
# Get all recent events
events = stream.recent()
print(f"Total events: {len(events)}")

# Filter by kind
tool_events = [e for e in stream.recent() if e.kind == "tool"]

# Time range
from datetime import datetime, timedelta
recent_hour = [
    e for e in stream.recent()
    if e.timestamp > datetime.now() - timedelta(hours=1)
]
```

### Event Visualization

```python
for event in stream.recent()[-20:]:
    emoji_map = {
        "tool": "🔧",
        "decision": "🤔",
        "error": "❌",
        "milestone": "🎯",
        "system": "⚙️"
    }
    emoji = emoji_map.get(event.kind, "📍")
    time_str = event.timestamp.strftime("%H:%M:%S")
    print(f"{emoji} [{time_str}] {event.message}")
```

---

## Safety & Approval Policies

Control execution of sensitive commands.

### Approval Modes

```python
from weebot.core.approval_policy import ExecApprovalPolicy, ApprovalMode

# AUTO: execute all (development)
policy = ExecApprovalPolicy(mode=ApprovalMode.AUTO)

# ALWAYS_ASK: require approval for everything
policy = ExecApprovalPolicy(mode=ApprovalMode.ALWAYS_ASK)

# DENY: reject all (safest)
policy = ExecApprovalPolicy(mode=ApprovalMode.DENY)
```

### Command Rules

```python
from weebot.core.approval_policy import CommandRule, RuleAction

policy = ExecApprovalPolicy(mode=ApprovalMode.AUTO)

# Allow specific commands
policy.allow_command("git status")
policy.allow_command("echo")

# Deny dangerous commands
policy.deny_command("rm -rf /")
policy.deny_command("shutdown")
```

### Approval Workflow

```python
# Evaluate before execution
result = policy.evaluate("rm -rf ~/data")

if result == ApprovalMode.DENY:
    print("Command blocked!")
elif result == ApprovalMode.ALWAYS_ASK:
    print("Requires manual approval")
else:
    print("Approved, proceeding...")
```

---

## MCP Server Integration

Run weebot as an MCP server for Claude Desktop.

### Starting the Server

```bash
# Run MCP server
python run_mcp.py

# Server output:
# MCP server running on stdio
# Available tools: bash, python_execute, web_search, file_editor
# Resources: activity, state, schedule
```

### Claude Desktop Configuration

Add to `~/.claude/profiles/default/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "weebot": {
      "command": "python",
      "args": ["C:/path/to/weebot/run_mcp.py"]
    }
  }
}
```

### MCP Resources

Available in Claude Desktop:

```
weebot://activity    - Current activity stream
weebot://state       - Project/task state
weebot://schedule    - Scheduled jobs
```

### Testing Connectivity

```bash
python run_mcp.py --ping
# Output: PONG (server healthy)
```

---

## Production Workflows

### 1. Automated Data Pipeline

```python
async def data_pipeline():
    bash = BashTool()
    python = PythonExecuteTool()
    editor = StrReplaceEditorTool()

    # Extract
    result = await bash.execute("curl https://api.example.com/data > raw.csv")
    
    # Transform
    code = "import pandas as pd; df = pd.read_csv('raw.csv'); print(df.describe())"
    result = await python.execute(code=code)
    
    # Load
    await bash.execute("psql -c 'COPY table FROM raw.csv'")
    
    # Report
    report = f"Pipeline completed: {result.output}"
    await editor.execute("create", "report.txt", report)
```

### 2. Intelligent Research Agent

```python
async def research_agent(topic: str):
    search = WebSearchTool()
    python = PythonExecuteTool()
    editor = StrReplaceEditorTool()
    
    # Search
    search_result = await search.execute(query=topic, num_results=5)
    
    # Analyze
    code = f"""
import re
text = {repr(search_result.output)}
keywords = re.findall(r'\\b[a-z]{{4,}}\\b', text.lower())
from collections import Counter
print(Counter(keywords).most_common(10))
"""
    analysis = await python.execute(code=code)
    
    # Report
    report = f"# Research Report: {topic}\\n\\n{search_result.output}\\n\\n{analysis.output}"
    await editor.execute("create", f"research_{topic.replace(' ', '_')}.md", report)
```

### 3. System Monitoring Dashboard

```python
async def monitoring_dashboard():
    bash = BashTool()
    scheduler = SchedulerTool()
    stream = ActivityStream()
    
    # Schedule health checks
    await scheduler.execute(
        action="add_job",
        job_id="health-check",
        job_type="interval",
        minutes=5,
        func_name="check_system_health"
    )
    
    # Run on-demand check
    result = await bash.execute("df -h && free -h && ps aux | head -20")
    stream.push("monitor", "metric", result.output)
    
    # Report
    print("Dashboard updated")
```

---

## Quick Reference

| Tool | Purpose | Example |
|------|---------|---------|
| **BashTool** | System commands, git, processes | `bash.execute("git status")` |
| **PythonExecuteTool** | Data analysis, ML, calculations | `python.execute(code)` |
| **WebSearchTool** | Research, information gathering | `search.execute("query")` |
| **StrReplaceEditorTool** | File creation, editing, automation | `editor.execute("create", path, text)` |
| **AdvancedBrowserTool** | Web automation, form filling, scraping | `browser.execute("navigate", url)` |
| **SchedulerTool** | Recurring jobs, cron tasks | `scheduler.execute("add_job", ...)` |
| **StateManager** | Persistent storage, database | `state.save_project(project)` |
| **ActivityStream** | Event tracking, monitoring | `stream.push(agent_id, kind, msg)` |

---

## Getting Started

1. **Run the showcase**: `python examples/06_comprehensive_capabilities_showcase.py`
2. **Review examples**: Check `examples/01-05` for specific workflows
3. **Start your own agent**: Use these patterns in your code
4. **Deploy**: Run `python run_mcp.py` for Claude Desktop integration

---

**Last Updated**: 2026-03-02
**Weebot Version**: 1.0.0
