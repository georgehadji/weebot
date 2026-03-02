# Connecting weebot to Claude Desktop

This guide shows how to run weebot as an MCP server so Claude Desktop can use
its tools directly in conversation — no coding required after setup.

## What you get

| Tool | What it does |
|------|-------------|
| `bash` | Run PowerShell (or WSL2 bash) commands |
| `python_execute` | Execute Python code in a sandboxed subprocess |
| `web_search` | DuckDuckGo + Bing search |
| `file_editor` | View, create, and edit files |
| `ping` | Health check — confirms the server is reachable |

Resources automatically provided to Claude:

| Resource | Content |
|----------|---------|
| `weebot://activity` | Recent tool calls (ring buffer, newest-first) |
| `weebot://state` | Live project state snapshot |
| `weebot://schedule` | Scheduled jobs list |

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.10+ | `python --version` |
| Claude Desktop | [Download](https://claude.ai/download) |
| At least one AI API key | OpenAI, Anthropic, Kimi, or DeepSeek |

---

## Step 1 — Install weebot dependencies

```bash
cd E:\path\to\weebot
pip install -r requirements.txt
```

---

## Step 2 — Create your `.env` file

```bash
copy .env.example .env
```

Open `.env` and fill in at least one API key:

```dotenv
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Step 3 — Verify the server starts

```bash
python run_mcp.py --help
```

Expected output:

```
usage: run_mcp [-h] [--transport {stdio,sse}] [--host HOST] [--port PORT]

weebot MCP server — connects Claude Desktop or Claude IDE to weebot tools ...
```

Test a dry run (Ctrl-C after a second — it will wait for MCP input on stdin):

```bash
python run_mcp.py
```

Check `logs/mcp.log` to confirm it started cleanly.

---

## Step 4 — Configure Claude Desktop

Open your Claude Desktop config file:

| OS | Path |
|----|------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

Add the following (adjust the path):

```json
{
  "mcpServers": {
    "weebot": {
      "command": "python",
      "args": [
        "E:\\path\\to\\weebot\\run_mcp.py"
      ],
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

> You can also omit `"env"` if your API keys are already in the system
> environment or in a `.env` file in the weebot directory.

A ready-to-edit template is available at `claude_desktop_config.json.example`.

---

## Step 5 — Restart Claude Desktop

Fully quit and reopen Claude Desktop.  The MCP server starts automatically
when Claude Desktop launches.

---

## Step 6 — Verify the connection

In a new Claude conversation type:

> *ping weebot*

Claude should respond with something like:

```json
{"status": "ok", "version": "1.0.0", "timestamp": "2026-03-02T12:00:00+00:00"}
```

You can now use all weebot tools naturally in conversation:

- *"Search the web for Python asyncio best practices"*
- *"Run `Get-Process` in PowerShell and show me the top 5 by CPU"*
- *"Execute this Python snippet: `print(2 ** 32)`"*
- *"Read the file C:\Users\me\notes.txt"*

---

## SSE transport (Claude IDE / remote access)

If you need to connect from Claude IDE or a web client instead of Claude Desktop,
start the server in SSE mode:

```bash
python run_mcp.py --transport sse --port 8765
```

Then connect your client to `http://127.0.0.1:8765/sse`.

---

## Troubleshooting

### `[weebot] Configuration error: ...`
No API key was found.  Set at least one in `.env` or in the `"env"` block of
`claude_desktop_config.json`.

### Server starts but tools don't appear in Claude Desktop
- Confirm the **full absolute path** to `run_mcp.py` in the config.
- Check `logs/mcp.log` for startup errors.
- Restart Claude Desktop after any config change.

### `ModuleNotFoundError: No module named 'weebot'`
Run `pip install -r requirements.txt` from the weebot root, or ensure your
`command` in the config uses the Python interpreter from the correct venv.

### `fastmcp` / `mcp` import errors
```bash
pip install "mcp>=1.5"
```

### `StateManager` or `SchedulerTool` warnings in `mcp.log`
These are non-fatal; the server still starts and all tools work.  The
`weebot://state` and `weebot://schedule` resources will return stubs
instead of live data until the managers are available.
